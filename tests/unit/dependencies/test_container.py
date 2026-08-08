"""Composition root wiring.

The container is what makes every other component replaceable. These tests pin
the guarantees the rest of the architecture leans on: lifetimes are what they
claim to be, and any registration can be substituted in a test.
"""

from __future__ import annotations

import pytest

from agent_platform.application.chat_service import ChatService
from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import (
    Environment,
    MockProviderSettings,
    PlatformSettings,
)
from agent_platform.dependencies.container import ApplicationContainer, build_llm_providers
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_shared.clock import Clock, SystemClock

pytestmark = pytest.mark.unit


@pytest.fixture
def container(test_settings: PlatformSettings) -> ApplicationContainer:
    return ApplicationContainer(settings=test_settings)


class TestResolution:
    """Everything declared must actually resolve."""

    def test_settings_resolve_to_the_supplied_instance(
        self, container: ApplicationContainer, test_settings: PlatformSettings
    ) -> None:
        assert container.settings() is test_settings

    def test_clock_resolves_to_a_clock(self, container: ApplicationContainer) -> None:
        clock = container.clock()

        assert isinstance(clock, SystemClock)
        # Structural check: consumers depend on the protocol, not the class.
        assert isinstance(clock, Clock)

    def test_health_service_resolves_with_its_dependencies_injected(
        self, container: ApplicationContainer, test_settings: PlatformSettings
    ) -> None:
        service = container.health_service()

        assert isinstance(service, HealthService)
        assert service._settings is test_settings  # noqa: SLF001 - asserting wiring


class TestLLMGatewayWiring:
    """The gateway is the only path to a model, so its wiring is load-bearing."""

    def test_the_gateway_resolves_and_satisfies_the_contract(
        self, container: ApplicationContainer
    ) -> None:
        gateway = container.llm_gateway()

        assert isinstance(gateway, DefaultLLMGateway)
        # Consumers depend on the protocol; the container is the only place the
        # implementation is named.
        assert isinstance(gateway, LLMGateway)

    def test_the_gateway_takes_its_policies_from_configuration(
        self, container: ApplicationContainer, test_settings: PlatformSettings
    ) -> None:
        """A hardcoded timeout would be a deployment that cannot be tuned."""
        gateway = container.llm_gateway()

        assert gateway._timeout_policy is test_settings.llm_gateway.timeout  # noqa: SLF001
        assert gateway._retry_policy is test_settings.llm_gateway.retry  # noqa: SLF001


class TestProviderRegistration:
    """Which providers exist is a configuration decision, resolved here."""

    def test_no_provider_is_registered_when_the_mock_is_disabled(
        self, test_settings: PlatformSettings
    ) -> None:
        """The default. Azure AI Foundry becomes the first always-on provider in M05."""
        assert build_llm_providers(test_settings) == ()

    def test_the_mock_provider_is_registered_when_enabled(
        self, test_settings: PlatformSettings
    ) -> None:
        enabled = test_settings.model_copy(
            update={"mock_provider": MockProviderSettings(enabled=True)}
        )

        registered = build_llm_providers(enabled)

        assert len(registered) == 1
        assert isinstance(registered[0], MockLLMProvider)
        assert isinstance(registered[0], LLMProvider)

    def test_the_mock_provider_is_refused_in_a_production_like_environment(
        self, test_settings: PlatformSettings
    ) -> None:
        """Second line of defence. Configuration validation already rejects this.

        Belt and braces on purpose: the settings invariant protects a correctly
        constructed `PlatformSettings`, and this protects the case where one is
        assembled some other way — a test, a future factory, a migration script.
        """
        production_with_mock = test_settings.model_copy(
            update={
                "app": test_settings.app.model_copy(update={"environment": Environment.PRODUCTION}),
                "mock_provider": MockProviderSettings(enabled=True),
            }
        )

        assert build_llm_providers(production_with_mock) == ()


class TestChatWiring:
    """The chat service is what the API layer resolves per request."""

    def test_the_chat_service_resolves_with_its_collaborators(
        self, container: ApplicationContainer
    ) -> None:
        service = container.chat_service()

        assert isinstance(service, ChatService)
        # Depends on the protocols, never on DefaultLLMGateway or a concrete
        # memory implementation.
        assert isinstance(service._gateway, LLMGateway)  # noqa: SLF001 - asserting wiring
        assert isinstance(service._memory, MemoryProvider)  # noqa: SLF001

    def test_memory_is_shared_across_resolutions(self, container: ApplicationContainer) -> None:
        """A per-request memory provider would lose the conversation every request."""
        assert container.memory_provider() is container.memory_provider()

    def test_memory_takes_its_bounds_from_configuration(
        self, container: ApplicationContainer, test_settings: PlatformSettings
    ) -> None:
        memory = container.memory_provider()

        assert memory._max_conversations == test_settings.memory.max_conversations  # noqa: SLF001
        assert (
            memory._max_messages  # noqa: SLF001
            == test_settings.memory.max_messages_per_conversation
        )

    def test_every_registered_component_is_probed_for_health(
        self, container: ApplicationContainer
    ) -> None:
        """`/ready` must report the real state of the system, not just the process."""
        service = container.health_service()

        probed = {provider.provider_id for provider in service._providers}  # noqa: SLF001

        assert "session-memory" in probed


class TestLifetimes:
    """A wrong lifetime is a bug that only shows up under concurrency."""

    def test_singletons_are_reused(self, container: ApplicationContainer) -> None:
        assert container.clock() is container.clock()
        assert container.health_service() is container.health_service()

    def test_separate_containers_do_not_share_singletons(
        self, test_settings: PlatformSettings
    ) -> None:
        """Test isolation depends on this."""
        first = ApplicationContainer(settings=test_settings)
        second = ApplicationContainer(settings=test_settings)

        assert first.clock() is not second.clock()


class TestOverrides:
    """Substitutability is the whole point of the container."""

    def test_a_registration_can_be_overridden(
        self, container: ApplicationContainer, test_settings: PlatformSettings
    ) -> None:
        replacement = HealthService(settings=test_settings, clock=SystemClock())
        container.health_service.override(replacement)

        assert container.health_service() is replacement

    def test_an_override_can_be_reset(self, container: ApplicationContainer) -> None:
        original = container.clock()
        container.clock.override(SystemClock())

        assert container.clock() is not original

        container.clock.reset_override()

        assert container.clock() is original


class TestRequiredDependencies:
    """Settings are supplied, never constructed here."""

    def test_settings_must_be_provided(self) -> None:
        """Configuration is validated before the container exists.

        A container that could build its own settings would let an unvalidated
        configuration reach the object graph.
        """
        container = ApplicationContainer()

        with pytest.raises(Exception, match=r"(?i)dependency|provider|settings"):
            container.settings()
