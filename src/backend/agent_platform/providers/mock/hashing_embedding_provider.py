"""A local embedding provider that needs no model.

Exists so the whole RAG pipeline — chunk, embed, index, retrieve, answer — runs
on a laptop and in CI with nothing provisioned and nothing billed. That is what
``CLAUDE.md`` requires: *"Everything should work using docker compose up without
manual setup."*

How it works, and what that buys
    Each text is hashed into a bag of character trigrams, and each trigram is
    hashed to a dimension. Texts sharing trigrams share dimensions, so the
    vectors of related texts point in similar directions. It is the *hashing
    trick*, and it is a real, deterministic lexical embedding — not a random
    vector wearing a costume.

What it is emphatically not
    Semantic. It matches on shared character sequences, so "car" and
    "automobile" are as unrelated as "car" and "carpet" are related. Any
    retrieval quality judgement made against this provider is a judgement about
    string overlap.

    That is stated here, in the class, and again in its health check, because
    the failure mode of a plausible fake is that somebody eventually believes
    it. Configuration refuses to use it in staging or production for exactly
    this reason.

Why not a real local model
    A sentence-transformer would be genuinely semantic, and it costs a few
    hundred megabytes of PyTorch plus a model download in every container and CI
    run. For a development default whose job is to make the pipeline runnable,
    that is a large price for a property nobody should be relying on in
    development anyway.
"""

from __future__ import annotations

import hashlib
import math
import re

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["HashingEmbeddingProvider"]

_logger = get_logger(__name__)

#: Length of the character sequences hashed into dimensions. Three is the usual
#: choice for lexical matching: long enough to carry a little word shape, short
#: enough that related words still collide.
_TRIGRAM = 3

#: Everything that is not a letter or digit becomes a space, so punctuation and
#: casing do not fragment the trigrams of otherwise identical text.
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


class HashingEmbeddingProvider:
    """Deterministic lexical embeddings, computed locally.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.embedding_provider.EmbeddingProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        dimensions: int = 256,
        provider_id: str = "hashing-embeddings",
    ) -> None:
        """Create the provider.

        Args:
            dimensions: Vector length. 256 is enough that unrelated texts rarely
                collide across every dimension, and small enough that brute-force
                scoring over a development corpus is instant.
            provider_id: Identifier it registers under.
        """
        self._dimensions = dimensions
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    @property
    def dimensions(self) -> int:
        """Length of the vectors this provider emits."""
        return self._dimensions

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Nothing to open."""
        _logger.info(
            "embeddings.initialized",
            provider_id=self._provider_id,
            dimensions=self._dimensions,
            detail=(
                "Local hashing embeddings. Lexical, not semantic — retrieval "
                "matches shared character sequences, not meaning."
            ),
        )

    async def close(self) -> None:
        """Nothing to release."""

    def supports(self, capability: Capability) -> bool:
        """Embeddings, and nothing else."""
        return capability is Capability.EMBEDDINGS

    async def health_check(self) -> ComponentHealth:
        """Report healthy, and say plainly what this provider is.

        DEGRADED was considered and rejected: nothing is wrong, and a component
        permanently degraded in normal development teaches people to ignore the
        dashboard. The warning belongs in the detail, which is where someone
        reading health output will see it.
        """
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=(
                f"Local hashing embeddings at {self._dimensions} dimensions. "
                "Lexical only — retrieval quality here says nothing about a real "
                "embedding model."
            ),
        )

    # -- Embeddings --------------------------------------------------------

    async def embed(
        self,
        texts: tuple[str, ...],
        context: ExecutionContext,
    ) -> tuple[tuple[float, ...], ...]:
        """Embed ``texts``, one vector per input in the same order."""
        del context
        return tuple(self._embed_one(text) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        """Hash one text into a normalised term-frequency vector."""
        buckets = [0.0] * self._dimensions

        for trigram in _trigrams(text):
            # Blake2b with a small digest: fast, well distributed, and stable
            # across processes and Python versions — unlike `hash()`, which is
            # randomised per process and would produce a different index on
            # every restart.
            digest = hashlib.blake2b(trigram.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self._dimensions
            buckets[bucket] += 1.0

        magnitude = math.sqrt(sum(value * value for value in buckets))
        if magnitude == 0.0:
            # Text with nothing hashable — punctuation, or shorter than a
            # trigram. A zero vector scores zero against everything, which is
            # the honest answer, and it keeps ingestion from failing over one
            # odd passage.
            return tuple(buckets)

        return tuple(value / magnitude for value in buckets)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"HashingEmbeddingProvider(dimensions={self._dimensions})"


def _trigrams(text: str) -> list[str]:
    """Return the character trigrams of ``text``, word by word.

    Trigrams are taken within words rather than across the whole string, so word
    order does not change the vector and two documents using the same vocabulary
    in different sentences still match.
    """
    normalised = _NON_WORD.sub(" ", text.lower())
    trigrams: list[str] = []

    for word in normalised.split():
        # Padded so short words still produce a trigram, and so word boundaries
        # contribute: " to " and "stop" should not look alike.
        padded = f" {word} "
        trigrams.extend(
            padded[index : index + _TRIGRAM] for index in range(len(padded) - _TRIGRAM + 1)
        )

    return trigrams
