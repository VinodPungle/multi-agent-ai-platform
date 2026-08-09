"""Embeddings from Azure AI Foundry.

The same resource, the same credential and the same keyless posture as the chat
provider — a different client on the same endpoint. `DefaultAzureCredential`
throughout: `az login` locally, Managed Identity in Azure, no API key accepted,
stored or logged.

Batching is the caller's lever, not this class's
    :meth:`embed` sends exactly what it is given, in one request. It does not
    split a large batch, because the right batch size depends on the deployment's
    limits, and a class that silently fragmented a request would hide a quota
    problem behind a slower answer. The indexer batches; this reports what
    happened.

Dimensionality is configuration
    An index is built at one dimensionality and cannot accept another. The value
    is declared in settings and checked at startup against whatever the store
    expects, rather than discovered on the first write — by which point half a
    corpus may be indexed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from azure.ai.inference.aio import EmbeddingsClient
from azure.core.exceptions import AzureError

from agent_platform.exceptions.base import ProviderError
from agent_platform.security.credentials import COGNITIVE_SERVICES_SCOPE
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.types.enums import Capability, HealthStatus

if TYPE_CHECKING:
    from azure.core.credentials_async import AsyncTokenCredential

__all__ = ["AzureFoundryEmbeddingProvider"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class AzureFoundryEmbeddingProvider:
    """Embeds text using a Foundry embedding deployment.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.embedding_provider.EmbeddingProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        credential: AsyncTokenCredential,
        dimensions: int,
        provider_id: str = "azure-foundry-embeddings",
        client: EmbeddingsClient | None = None,
    ) -> None:
        """Create the provider.

        Args:
            endpoint: Foundry inference endpoint.
            deployment: Embedding deployment name.
            credential: Built in the composition root, so this class never
                touches the credential chain and tests never need to.
            dimensions: Vector length this deployment emits. Declared rather
                than probed — probing costs a billed call at startup, and the
                value is a property of the deployment an operator already knows.
            provider_id: Identifier it registers under.
            client: Injected client, so the whole provider is exercisable
                without a network.
        """
        self._endpoint = endpoint
        self._deployment = deployment
        self._credential = credential
        self._dimensions = dimensions
        self._provider_id = provider_id
        self._client = client
        self._owns_client = client is None

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    @property
    def dimensions(self) -> int:
        """Length of the vectors this deployment emits."""
        return self._dimensions

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Open the client. Deliberately makes no call."""
        if self._client is None:
            self._client = EmbeddingsClient(
                endpoint=self._endpoint,
                credential=self._credential,
                credential_scopes=[COGNITIVE_SERVICES_SCOPE],
                model=self._deployment,
            )

        _logger.info(
            "embeddings.initialized",
            provider_id=self._provider_id,
            deployment=self._deployment,
            dimensions=self._dimensions,
            auth="DefaultAzureCredential",
        )

    async def close(self) -> None:
        """Close the client and the credential.

        The credential holds its own HTTP session and token cache; leaving it
        open leaks a connection pool per restart in a long-lived host.
        """
        try:
            if self._client is not None and self._owns_client:
                await self._client.close()
                self._client = None
        finally:
            if self._owns_client:
                await self._credential.close()

    def supports(self, capability: Capability) -> bool:
        """Embeddings, and nothing else."""
        return capability is Capability.EMBEDDINGS

    async def health_check(self) -> ComponentHealth:
        """Report configuration, not reachability.

        The same choice the chat provider makes and for the same reason: a probe
        that embedded text would bill for every readiness poll, and would wake a
        scale-to-zero deployment on a schedule. Connectivity is proven by the
        first real request.
        """
        if self._client is None:
            return ComponentHealth(
                name=self._provider_id,
                status=HealthStatus.UNKNOWN,
                detail="Not initialised.",
            )

        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=(
                f"Configured for deployment {self._deployment!r} at "
                f"{self._dimensions} dimensions. Not probed — a probe would be billed."
            ),
        )

    # -- Embeddings --------------------------------------------------------

    async def embed(
        self,
        texts: tuple[str, ...],
        context: ExecutionContext,
    ) -> tuple[tuple[float, ...], ...]:
        """Embed ``texts``, one vector per input in the same order.

        Order is load-bearing: the indexer pairs the results back to the chunks
        it sent by position, so a provider that reordered would attach every
        passage to the wrong text — a corruption that produces plausible-looking
        nonsense rather than an error.

        Raises:
            ProviderError: the deployment rejected the request or was
                unreachable. Ingestion should stop and be retried rather than
                write a partially embedded corpus.
        """
        if not texts:
            return ()

        client = self._require_client()

        with _tracer.start_as_current_span("embeddings.embed") as span:
            span.set_attribute("embeddings.provider_id", self._provider_id)
            span.set_attribute("embeddings.deployment", self._deployment)
            span.set_attribute("embeddings.batch_size", len(texts))
            # The texts themselves are not a span attribute: they are document
            # content, and spans are exported to systems with different
            # retention and access rules.

            try:
                result = await client.embed(input=list(texts))
            except AzureError as error:
                _logger.warning(
                    "embeddings.failed",
                    provider_id=self._provider_id,
                    error_type=type(error).__name__,
                    batch_size=len(texts),
                    **context.to_log_fields(),
                )
                message = (
                    f"Embedding provider {self._provider_id!r} could not embed "
                    f"{len(texts)} text(s) ({type(error).__name__})."
                )
                raise ProviderError(message, provider_id=self._provider_id) from error

        # Sorted by the index the service reports rather than trusting response
        # order. The API documents one embedding per input carrying its index;
        # relying on arrival order instead would be an assumption that fails
        # silently and corrupts the index.
        items = sorted(result.data, key=lambda item: item.index)
        vectors = tuple(tuple(float(value) for value in item.embedding) for item in items)

        if len(vectors) != len(texts):
            message = (
                f"Embedding provider {self._provider_id!r} returned {len(vectors)} "
                f"vector(s) for {len(texts)} input(s). Refusing to index a "
                "mismatched batch."
            )
            raise ProviderError(message, provider_id=self._provider_id)

        return vectors

    def _require_client(self) -> EmbeddingsClient:
        """Return the client, or fail with an actionable message."""
        if self._client is None:
            message = (
                f"Embedding provider {self._provider_id!r} was not initialised. "
                "This is a wiring error: initialise() runs during application startup."
            )
            raise ProviderError(message, provider_id=self._provider_id)
        return self._client

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"AzureFoundryEmbeddingProvider(deployment={self._deployment!r})"
