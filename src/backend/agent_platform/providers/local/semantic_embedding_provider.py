"""Semantic embeddings computed locally, with no cloud dependency.

The provider that makes retrieval mean something without an Azure deployment.
`HashingEmbeddingProvider` matches shared character sequences — "car" and
"automobile" are unrelated to it — which is fine for proving the pipeline runs
and useless for judging whether retrieval works. This one embeds *meaning*.

Model
    `BAAI/bge-small-en-v1.5` by default: 384 dimensions, 67 MB, and near the top
    of the retrieval benchmarks for its size. Larger models in the same family
    are a configuration change, and the trade is straightforward — `bge-large`
    is roughly eighteen times the download for a few points of accuracy.

ONNX, not PyTorch
    `fastembed` runs the model through `onnxruntime`. A sentence-transformers
    setup would pull PyTorch — well over a gigabyte — to do the same job. This
    is around 200 MB of packages plus the model, which is the difference between
    "optional extra" and "nobody installs it".

Two things this class must get right, and both are easy to get wrong
    **The model is loaded during initialisation**, not on first use. Otherwise
    the first user to ask a question waits for a 67 MB download, and a cold
    replica looks broken rather than slow.

    **Embedding runs in a thread**, because `fastembed.embed` is synchronous and
    CPU-bound. Calling it directly on the event loop stalls every other request
    in the process for the duration — on a batch of documents, that is seconds.

Why it is optional, and why hashing still exists
    It costs a dependency group and a model download from a third party at first
    run. CI has neither the time nor, reliably, the network — so the test suite
    keeps using the hashing provider, which is deterministic and offline. This
    exists so a developer can judge retrieval quality honestly, and so a
    deployment that cannot reach Azure OpenAI still has a real option.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agent_platform.exceptions.base import ConfigurationError, ProviderError
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.types.enums import Capability, HealthStatus

if TYPE_CHECKING:
    from fastembed import TextEmbedding

__all__ = ["DEFAULT_LOCAL_MODEL", "LocalSemanticEmbeddingProvider"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

#: Small, fast, and genuinely good at retrieval. 384 dimensions, 67 MB.
DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"


class LocalSemanticEmbeddingProvider:
    """Embeds text with a local ONNX sentence-embedding model.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.embedding_provider.EmbeddingProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_LOCAL_MODEL,
        dimensions: int = 384,
        provider_id: str = "local-semantic-embeddings",
        cache_directory: str | None = None,
    ) -> None:
        """Create the provider.

        Args:
            model_name: A model `fastembed` supports.
            dimensions: Vector length the model emits. Declared so a mismatch
                with the index is caught at startup — and checked against the
                model once it loads, because a wrong value here would build an
                index nothing can search.
            provider_id: Identifier it registers under.
            cache_directory: Where the model is stored. `None` uses fastembed's
                default. Worth setting to a mounted volume in a container, so a
                restart does not re-download 67 MB.
        """
        self._model_name = model_name
        self._dimensions = dimensions
        self._provider_id = provider_id
        self._cache_directory = cache_directory
        self._model: TextEmbedding | None = None

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    @property
    def dimensions(self) -> int:
        """Length of the vectors this model emits."""
        return self._dimensions

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Load the model, downloading it if this is the first run.

        Deliberately at startup. Loading lazily would make the first user's
        question wait for a download, and a slow cold start is far easier to
        diagnose than a request that mysteriously takes thirty seconds once.

        Raises:
            ConfigurationError: `fastembed` is not installed, or the declared
                dimensionality does not match the model's.
        """
        model = await asyncio.to_thread(self._load)

        actual = _dimensions_of(self._model_name)
        if actual is not None and actual != self._dimensions:
            message = (
                f"Model {self._model_name!r} emits {actual}-dimensional vectors but "
                f"knowledge.embedding_dimensions is {self._dimensions}. An index is "
                "built at one dimensionality and cannot accept another."
            )
            raise ConfigurationError(message, details={"provider_id": self._provider_id})

        self._model = model
        _logger.info(
            "embeddings.initialized",
            provider_id=self._provider_id,
            model=self._model_name,
            dimensions=self._dimensions,
            detail="Local semantic embeddings. No network call per request, no cost.",
        )

    def _load(self) -> TextEmbedding:
        """Construct the model. Blocking, so callers run it in a thread."""
        try:
            from fastembed import TextEmbedding
        except ImportError as error:  # pragma: no cover - depends on the install
            message = (
                "Local semantic embeddings need the 'knowledge' extra. Install it with "
                "`uv sync --extra knowledge`, or set "
                "knowledge.embedding_provider to 'azure-foundry' or 'hashing'."
            )
            raise ConfigurationError(
                message,
                details={"provider_id": self._provider_id},
            ) from error

        return TextEmbedding(model_name=self._model_name, cache_dir=self._cache_directory)

    async def close(self) -> None:
        """Release the model."""
        self._model = None

    def supports(self, capability: Capability) -> bool:
        """Embeddings, and nothing else."""
        return capability is Capability.EMBEDDINGS

    async def health_check(self) -> ComponentHealth:
        """Report whether the model is loaded."""
        if self._model is None:
            return ComponentHealth(
                name=self._provider_id,
                status=HealthStatus.UNKNOWN,
                detail="Not initialised.",
            )

        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=(
                f"Local semantic model {self._model_name!r} at {self._dimensions} "
                "dimensions. Retrieval matches meaning, and costs nothing per query."
            ),
        )

    # -- Embeddings --------------------------------------------------------

    async def embed(
        self,
        texts: tuple[str, ...],
        context: ExecutionContext,
    ) -> tuple[tuple[float, ...], ...]:
        """Embed ``texts``, one vector per input in the same order.

        Raises:
            ProviderError: the provider was not initialised, or the model
                returned a different number of vectors than it was given —
                which would otherwise pair passages with the wrong embeddings
                and produce confident nonsense.
        """
        if not texts:
            return ()

        model = self._model
        if model is None:
            message = (
                f"Embedding provider {self._provider_id!r} was not initialised. "
                "This is a wiring error: initialise() runs during application startup."
            )
            raise ProviderError(message, provider_id=self._provider_id)

        with _tracer.start_as_current_span("embeddings.embed") as span:
            span.set_attribute("embeddings.provider_id", self._provider_id)
            span.set_attribute("embeddings.model", self._model_name)
            span.set_attribute("embeddings.batch_size", len(texts))
            # The texts are document and query content, and stay out of spans.

            # In a thread: `embed` is synchronous and CPU-bound, and running it
            # on the event loop would stall every other request in the process
            # for the duration — seconds, on a batch of documents.
            vectors = await asyncio.to_thread(self._embed_batch, model, texts)

        if len(vectors) != len(texts):
            message = (
                f"Embedding provider {self._provider_id!r} returned {len(vectors)} "
                f"vector(s) for {len(texts)} input(s). Refusing to index a "
                "mismatched batch."
            )
            raise ProviderError(message, provider_id=self._provider_id)

        return vectors

    @staticmethod
    def _embed_batch(
        model: TextEmbedding,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        """Run the model. Blocking; called through a thread.

        `fastembed` yields numpy arrays lazily. They are converted to tuples of
        floats here so nothing above this line depends on numpy — the vector
        store and the contracts are plain Python, and a numpy array leaking into
        them would work until something tried to serialise one.
        """
        return tuple(tuple(float(value) for value in vector) for vector in model.embed(texts))

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"LocalSemanticEmbeddingProvider(model={self._model_name!r})"


def _dimensions_of(model_name: str) -> int | None:
    """Return the dimensionality `fastembed` declares for a model.

    Returns ``None`` when the model is unknown to it, so an unrecognised name
    fails later with the model's own error rather than a confusing one from a
    dimensionality check that had nothing to compare against.
    """
    try:
        from fastembed import TextEmbedding
    except ImportError:  # pragma: no cover - depends on the install
        return None

    for description in TextEmbedding.list_supported_models():
        if description.get("model") == model_name:
            dimension: Any = description.get("dim")
            return int(dimension) if dimension is not None else None
    return None
