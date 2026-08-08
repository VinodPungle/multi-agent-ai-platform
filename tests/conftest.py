"""Shared pytest fixtures.

Two rules govern the whole suite:

* **No network access.** Unit tests exercise business logic through injected
  fakes. Anything that would open a socket belongs behind a provider interface,
  and the interface is what gets faked.
* **No shared application.** Every test that needs an app builds its own from
  explicit settings, so tests cannot leak configuration or container state into
  one another.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.api.app import create_app
from agent_platform.configuration.settings import (
    AppSettings,
    Environment,
    LoggingSettings,
    PlatformSettings,
    ServerSettings,
    TelemetrySettings,
    get_settings,
)

__all__ = [
    "FakeClock",
    "app",
    "client",
    "isolated_environment",
    "test_settings",
]


class FakeClock:
    """A controllable :class:`~agent_platform_shared.clock.Clock`.

    Latency assertions against the real clock are inherently flaky. Advancing
    time explicitly makes them exact.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        """Move both clocks forward by ``seconds``."""
        self._monotonic += seconds


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate every test from ambient configuration.

    Autouse and non-negotiable. Without it a developer's ``.env`` or an exported
    ``PLATFORM_*`` variable changes test outcomes, producing failures that
    reproduce on one machine and not another.
    """
    for key in list(os.environ):
        if key.startswith("PLATFORM_"):
            monkeypatch.delenv(key, raising=False)

    # `get_settings` memoises. A value cached by an earlier test would otherwise
    # be handed to the next one.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def test_settings() -> PlatformSettings:
    """Settings for an in-process test application.

    Telemetry is disabled: installing a global tracer provider per test leaks
    state across the session and the OpenTelemetry SDK refuses to replace one
    that is already set.
    """
    return PlatformSettings(
        app=AppSettings(
            name="test-platform",
            version="0.0.0-test",
            environment=Environment.TESTING,
            debug=True,
        ),
        server=ServerSettings(cors_origins=("http://localhost:5173",)),
        logging=LoggingSettings(level="DEBUG", renderer="json"),
        telemetry=TelemetrySettings(enabled=False),
    )


@pytest.fixture
def app(test_settings: PlatformSettings) -> FastAPI:
    """A fully wired application built from :func:`test_settings`."""
    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """An HTTP client for ``app``.

    Used as a context manager so the lifespan actually runs — without that,
    startup and shutdown code is never exercised by the suite.
    """
    with TestClient(app) as test_client:
        yield test_client
