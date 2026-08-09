"""Provider resolution through the model catalogue.

The resolver this replaces ignored ``model_id`` entirely — correct while one
provider was registered, since there was nothing to choose between. Routing
makes that assumption false: a policy can now choose a model, and the model
knows which provider serves it, so resolution has to follow the model rather
than a configured default.

Without this, routing would be decorative. A decision to use a model on a second
provider would resolve to the default provider, which would be asked for a model
it has never heard of — and the failure would arrive from the provider, naming
the model, with nothing pointing at the resolution step that caused it.

What it still refuses to do
    No failover, no fallback model, no health-based exclusion. All three change
    which model answered a user with nothing in the request recording it. If a
    model should be avoided, ``is_available`` withdraws it from routing where
    the decision is visible and attributable — see
    :mod:`agent_platform_sdk.interfaces.llm_provider_resolver`.
"""

from __future__ import annotations

from agent_platform.exceptions.base import ConfigurationError, NotFoundError
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.registry import Registry

__all__ = ["RegistryBackedProviderResolver"]


class RegistryBackedProviderResolver:
    """Resolves a model to the provider that registered it.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.llm_provider_resolver.LLMProviderResolver`
    structurally — no base class is inherited, per ADR-0004.
    """

    def __init__(
        self,
        providers: tuple[LLMProvider, ...],
        models: Registry[ModelDescriptor],
        default_provider_id: str | None = None,
    ) -> None:
        """Create the resolver.

        Args:
            providers: Registered LLM providers.
            models: The catalogue, which maps a model to the provider that
                advertised it.
            default_provider_id: Used only when a model is not in the catalogue
                — see :meth:`resolve`.

        Raises:
            ConfigurationError: two providers share a ``provider_id``, or the
                configured default names one that is not registered. Both are
                startup mistakes and both are far cheaper to find here than in a
                request.
        """
        by_id: dict[str, LLMProvider] = {}
        for provider in providers:
            if provider.provider_id in by_id:
                message = (
                    f"Duplicate LLM provider id {provider.provider_id!r}. "
                    "Each provider must be registered under a unique id."
                )
                raise ConfigurationError(message, details={"provider_id": provider.provider_id})
            by_id[provider.provider_id] = provider

        if default_provider_id is not None and default_provider_id not in by_id:
            message = (
                f"Configured default LLM provider {default_provider_id!r} is not registered. "
                f"Registered providers: {sorted(by_id) or 'none'}."
            )
            raise ConfigurationError(message, details={"provider_id": default_provider_id})

        self._providers = by_id
        self._models = models
        self._default_provider_id = default_provider_id

    async def resolve(self, model_id: str, context: ExecutionContext) -> LLMProvider:
        """Return the provider that serves ``model_id``.

        Order of precedence:

        1. ``context.provider_id`` — the runtime set it from a routing decision,
           or an operator pinned it. Deliberately ahead of the catalogue: when
           two providers serve the same model id (a failover pair, or one
           open-weight model on two hosts) only the first is in the catalogue,
           and the decision is what says which was actually chosen.
        2. The catalogue entry for ``model_id``.
        3. The configured default, then the sole registered provider.

        Raises:
            NotFoundError: nothing is registered, the named provider is unknown,
                or several are registered with no way to choose between them.
        """
        if not self._providers:
            message = (
                "No LLM provider is registered. Register one in the composition root "
                "before invoking a model."
            )
            raise NotFoundError(message, details={"model_id": model_id})

        descriptor = self._models.try_get(model_id)
        requested_id = (
            context.provider_id
            or (descriptor.provider_id if descriptor is not None else None)
            or self._default_provider_id
        )

        if requested_id is None:
            if len(self._providers) == 1:
                return next(iter(self._providers.values()))
            message = (
                f"Model {model_id!r} is not in the catalogue, several providers are "
                "registered, and no default is configured. Set "
                "llm_gateway.default_provider_id, or pin one on the execution context."
            )
            raise NotFoundError(
                message,
                details={"model_id": model_id, "registered": sorted(self._providers)},
            )

        provider = self._providers.get(requested_id)
        if provider is None:
            # Reached when a catalogue entry names a provider that is no longer
            # registered — a wiring mistake, not a user error, and worth saying
            # so rather than reporting a bare "unknown provider".
            message = (
                f"No LLM provider registered under id {requested_id!r} "
                f"(required by model {model_id!r})."
            )
            raise NotFoundError(
                message,
                details={
                    "provider_id": requested_id,
                    "model_id": model_id,
                    "registered": sorted(self._providers),
                },
            )
        return provider
