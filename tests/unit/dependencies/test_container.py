"""Composition root wiring.

The container is what makes every other component replaceable. These tests pin
the guarantees the rest of the architecture leans on: lifetimes are what they
claim to be, and any registration can be substituted in a test.
"""

from __future__ import annotations

import pytest

from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform.dependencies.container import ApplicationContainer
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
