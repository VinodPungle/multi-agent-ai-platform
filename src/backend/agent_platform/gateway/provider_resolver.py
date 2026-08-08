"""Provider resolution for the current, single-provider platform.

Resolution today is deliberately the smallest thing that satisfies the contract:
there is one provider, so there is nothing to choose between. What matters is
that the *seam* exists — the gateway asks a resolver rather than holding a
provider — so that Milestone 03 can substitute a registry-backed implementation
and a later policy engine can substitute a cost- or latency-aware one without
either touching the gateway.

Explicitly **not** implemented here, and not by accident:

* No failover. A provider that fails produces an error, not a quiet retry
  against a different vendor. Silent failover changes which model answered a
  user with nothing in the request recording it.
* No fallback model. Same reason.
* No health-based exclusion. That is a routing policy and belongs to the policy
  engine, which does not exist yet.
"""

from __future__ import annotations

from agent_platform.exceptions.base import ConfigurationError, NotFoundError
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.interfaces.llm_provider import LLMProvider

__all__ = ["ConfiguredProviderResolver"]


class ConfiguredProviderResolver:
    """Resolves against the providers registered in the composition root.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.llm_provider_resolver.LLMProviderResolver`
    structurally — no platform base class is inherited, per
    ``docs/adr/0004-provider-abstraction-via-protocols.md``.
    """

    def __init__(
        self,
        providers: tuple[LLMProvider, ...] = (),
        default_provider_id: str | None = None,
    ) -> None:
        """Create the resolver.

        Args:
            providers: Registered LLM providers. Empty until Milestone 05
                registers Azure AI Foundry — every resolution then fails with a
                clear error rather than a confusing ``None``.
            default_provider_id: Provider to use when the caller does not pin
                one. Required only once more than one provider is registered.

        Raises:
            ConfigurationError: two providers share a ``provider_id``, or the
                configured default names a provider that is not registered.
                Both are startup mistakes, and both are far cheaper to find here
                than in a request.
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
        self._default_provider_id = default_provider_id

    async def resolve(self, model_id: str, context: ExecutionContext) -> LLMProvider:
        """Return the provider that serves ``model_id``.

        Order of precedence:

        1. ``context.provider_id`` — an operator or policy pinned the provider.
        2. The configured default.
        3. The sole registered provider, when exactly one is registered.

        ``model_id`` does not participate yet: mapping a model to its provider
        requires the model registry, which arrives in Milestone 03. It is part
        of the signature now so that adding the lookup later changes only this
        method.

        Raises:
            NotFoundError: nothing is registered, the requested provider is
                unknown, or several are registered with no default to choose
                between them.
        """
        if not self._providers:
            message = (
                "No LLM provider is registered. Register one in the composition root "
                "before invoking a model."
            )
            raise NotFoundError(message, details={"model_id": model_id})

        requested_id = context.provider_id or self._default_provider_id

        if requested_id is None:
            if len(self._providers) == 1:
                return next(iter(self._providers.values()))
            message = (
                "Several LLM providers are registered and no default is configured. "
                "Set llm_gateway.default_provider_id, or pin one on the execution context."
            )
            raise NotFoundError(message, details={"registered": sorted(self._providers)})

        provider = self._providers.get(requested_id)
        if provider is None:
            message = f"No LLM provider registered under id {requested_id!r}."
            raise NotFoundError(
                message,
                details={"provider_id": requested_id, "registered": sorted(self._providers)},
            )
        return provider
