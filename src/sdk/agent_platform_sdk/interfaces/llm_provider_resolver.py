"""Provider-resolution port used by the LLM Gateway.

Separating *which provider* from *how the call is made* is what allows model
routing to become policy-driven later without touching the gateway. The gateway
asks this port for a provider; how the answer is produced is entirely the
resolver's business.

Implementations:

===============================  ====================================  ==========
Implementation                   Resolution strategy                   Milestone
===============================  ====================================  ==========
``RegistryBackedProviderResolver``  Model catalogue -> provider        09
===============================  ====================================  ==========

The earlier ``ConfiguredProviderResolver`` returned the single configured
provider and ignored ``model_id`` entirely — correct while one provider was
registered, and false the moment routing could choose a model on another. It was
removed rather than kept alongside: two implementations where only one is wired
is how a stale one drifts out of agreement with reality unnoticed.

*Choosing* a model is a separate concern and lives behind
:mod:`agent_platform_sdk.interfaces.model_router`. This port only answers where
the chosen model is served from.

No implementation may fail over to a second provider unless a policy explicitly
says so. Silent failover changes which model answered a user without anything in
the request recording it, and makes evaluation data incomparable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.interfaces.llm_provider import LLMProvider

__all__ = ["LLMProviderResolver"]


@runtime_checkable
class LLMProviderResolver(Protocol):
    """Answers "which provider serves this model?"."""

    async def resolve(self, model_id: str, context: ExecutionContext) -> LLMProvider:
        """Return the provider that serves ``model_id``.

        Asynchronous because a registry-backed implementation may consult a
        remote catalogue or a health probe. The current implementation returns
        immediately; declaring it async now avoids a breaking signature change
        when it stops being immediate.

        Args:
            model_id: Registry identifier of the model to be invoked.
            context: Execution context. ``context.provider_id``, when set by an
                operator or a policy, pins resolution to a named provider.

        Returns:
            A provider satisfying :class:`LLMProvider`.

        Raises:
            NotFoundError: no provider serves ``model_id``, or none is
                registered at all.
        """
        ...
