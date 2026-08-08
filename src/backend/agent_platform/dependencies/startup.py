"""Asynchronous startup and shutdown of the object graph.

The container wires objects; this brings them to life. Both steps exist because
construction is synchronous and initialisation is not: a provider opens
connections, a prompt provider reads files, and a real model catalogue is a
network call.

Doing it at startup rather than lazily is a deliberate "fail fast"
(``CLAUDE.md``): a misconfigured provider, an unreadable prompt or an agent
naming a model nothing serves should stop the process from starting, not surface
on a user's first request as an error nobody can attribute.
"""

from __future__ import annotations

from agent_platform.dependencies.container import ApplicationContainer
from agent_platform.exceptions.base import ConfigurationError
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["shutdown_platform", "start_platform"]

_logger = get_logger(__name__)


async def start_platform(container: ApplicationContainer) -> None:
    """Initialise every component and validate the wiring.

    Raises:
        ConfigurationError: an agent references a model no registered provider
            serves. Caught here rather than at call time because it is a
            configuration mistake, and the moment to report one is startup.
    """
    for component in _initialisable(container):
        await component.initialize()

    await _populate_model_registry(container)
    _validate_agents(container)

    _logger.info(
        "platform.wiring_verified",
        agents=list(container.agent_registry().keys()),
        providers=list(container.provider_registry().keys()),
        models=list(container.model_registry().keys()),
        workflow_engine=container.workflow_engine().engine_id,
    )


async def shutdown_platform(container: ApplicationContainer) -> None:
    """Release every component's resources.

    Failures are logged and swallowed. Shutdown runs while the process is going
    away regardless; raising here would replace a clean stop with a stack trace
    and could skip the remaining components' cleanup.
    """
    for component in _initialisable(container):
        try:
            await component.close()
        except Exception:
            _logger.warning(
                "platform.component_close_failed",
                provider_id=component.provider_id,
                exc_info=True,
            )


def _initialisable(container: ApplicationContainer) -> tuple[Provider, ...]:
    """Return every component with a lifecycle, in initialisation order.

    Prompts and memory first, inference last: an agent is useless without its
    prompt, and failing on the cheap local dependency before opening a network
    connection gives the clearer error.
    """
    return (
        container.prompt_provider(),
        container.memory_provider(),
        *container.llm_providers(),
    )


async def _populate_model_registry(container: ApplicationContainer) -> None:
    """Fill the model catalogue from the registered providers.

    Populated from providers rather than from configuration, so the catalogue
    cannot advertise a model that nothing can actually serve.
    """
    registry = container.model_registry()

    for provider in container.llm_providers():
        for model in await provider.list_models():
            if registry.contains(model.model_id):
                # Two providers serving one model id is legitimate (a failover
                # pair, the same open-weight model on two hosts). First
                # registration wins; the resolver decides which provider is
                # actually used.
                _logger.info(
                    "models.duplicate_id",
                    model_id=model.model_id,
                    provider_id=provider.provider_id,
                    detail="Already registered by another provider; keeping the first.",
                )
                continue
            registry.register(model.model_id, model)


def _validate_agents(container: ApplicationContainer) -> None:
    """Refuse to start if an agent names a model or provider that does not exist.

    A typo in ``PLATFORM_AGENT__MODEL_ID`` is otherwise invisible until someone
    sends a message, and then reports as a provider failure — which sends the
    reader looking in the wrong place entirely.

    Skipped entirely when *no* provider is registered, which is a legitimate
    state rather than a mistake: it is the default until Azure AI Foundry lands
    in Milestone 05, and it is what a deployment looks like with the mock
    provider correctly disabled. Every agent would fail this check, so failing
    startup would mean the platform could not boot at all — and the real
    condition is already reported clearly, both by the warning below and by the
    gateway's "No LLM provider is registered" at request time.
    """
    models = container.model_registry()
    providers = container.provider_registry()

    if not providers.keys():
        _logger.warning(
            "platform.no_inference_providers",
            agents=list(container.agent_registry().keys()),
            detail=(
                "No LLM provider is registered, so no agent can answer. "
                "Agent configuration is not validated in this state."
            ),
        )
        return

    problems: list[str] = []

    for agent_id, agent in container.agent_registry().items():
        descriptor = agent.descriptor

        if not providers.contains(descriptor.provider_id):
            problems.append(
                f"agent {agent_id!r} names provider {descriptor.provider_id!r}, "
                f"which is not registered (registered: {', '.join(providers.keys()) or 'none'})"
            )

        if not models.contains(descriptor.model_id):
            problems.append(
                f"agent {agent_id!r} names model {descriptor.model_id!r}, "
                f"which no provider serves (available: {', '.join(models.keys()) or 'none'})"
            )

    if problems:
        message = "Invalid agent configuration:\n  - " + "\n  - ".join(problems)
        raise ConfigurationError(message, details={"problems": problems})
