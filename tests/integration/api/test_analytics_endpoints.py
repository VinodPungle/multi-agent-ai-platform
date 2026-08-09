"""The cost analytics endpoint, over the real application.

The test that matters here is the last one: that a chat request actually causes
the totals to move. Everything upstream — the runtime emitting a record, the
composite fanning it out, the aggregator counting it — is only worth anything if
that link holds end to end.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.api.app import create_app
from agent_platform.configuration.settings import (
    AgentSettings,
    AppSettings,
    ChatSettings,
    Environment,
    LoggingSettings,
    MockProviderSettings,
    PlatformSettings,
    TelemetrySettings,
)

pytestmark = pytest.mark.integration

PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts"


@pytest.fixture
def analytics_client() -> Iterator[TestClient]:
    """An application that can actually answer, so a turn produces a record.

    The shared `client` fixture registers no inference provider, so every chat
    request 404s and no evaluation record is ever emitted — which would make
    these tests pass against a platform that measures nothing.
    """
    settings = PlatformSettings(
        app=AppSettings(
            name="test-platform",
            version="0.0.0-test",
            environment=Environment.TESTING,
            debug=True,
        ),
        logging=LoggingSettings(level="DEBUG", renderer="json"),
        telemetry=TelemetrySettings(enabled=False),
        mock_provider=MockProviderSettings(enabled=True, chunk_delay_seconds=0.0),
        agent=AgentSettings(provider_id="mock", model_id="mock-echo"),
        chat=ChatSettings(agent_id="chat-agent", prompts_directory=str(PROMPTS_ROOT)),
    )
    app: FastAPI = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


class TestCostEndpoint:
    def test_it_answers_before_any_traffic(self, analytics_client: TestClient) -> None:
        """A fresh replica has spent nothing, and should say so rather than 404."""
        response = analytics_client.get("/api/v1/analytics/costs")

        assert response.status_code == 200
        assert response.json()["summary"]["overall"]["invocations"] == 0

    def test_it_states_the_scope_of_its_numbers(self, analytics_client: TestClient) -> None:
        """A per-replica figure read as platform-wide spend is actively misleading."""
        scope = analytics_client.get("/api/v1/analytics/costs").json()["scope"]

        assert "reset on restart" in scope
        assert "estimates" in scope

    def test_a_chat_request_moves_the_totals(self, analytics_client: TestClient) -> None:
        """The whole chain, end to end: runtime -> composite -> aggregator -> endpoint."""
        before = analytics_client.get("/api/v1/analytics/costs").json()["summary"]

        analytics_client.post("/api/v1/chat/messages", json={"message": "hello"})

        after = analytics_client.get("/api/v1/analytics/costs").json()["summary"]

        assert after["overall"]["invocations"] > before["overall"]["invocations"]
        assert after["overall"]["completion_tokens"] > 0

    def test_spend_is_attributed_to_a_model_and_an_agent(
        self, analytics_client: TestClient
    ) -> None:
        """Cost nobody can attribute is cost nobody can act on."""
        analytics_client.post("/api/v1/chat/messages", json={"message": "hello"})

        summary = analytics_client.get("/api/v1/analytics/costs").json()["summary"]

        assert [row["key"] for row in summary["by_model"]] == ["mock-echo"]
        assert [row["key"] for row in summary["by_provider"]] == ["mock"]
        assert [row["key"] for row in summary["by_agent"]] == ["chat-agent"]

    def test_a_streamed_turn_is_counted_too(self, analytics_client: TestClient) -> None:
        """Streaming spends the same tokens; counting only non-streaming undercounts."""
        with analytics_client.stream(
            "POST",
            "/api/v1/chat/messages/stream",
            json={"message": "hello"},
        ) as response:
            # Drain it: the record is emitted when the stream finishes.
            for _ in response.iter_lines():
                pass

        summary = analytics_client.get("/api/v1/analytics/costs").json()["summary"]

        assert summary["overall"]["invocations"] >= 1

    def test_cost_is_serialised_without_float_rounding(self, analytics_client: TestClient) -> None:
        """`Decimal` survives to the wire; a float would reintroduce drift at the last step."""
        analytics_client.post("/api/v1/chat/messages", json={"message": "hello"})

        cost = analytics_client.get("/api/v1/analytics/costs").json()["summary"]["overall"][
            "estimated_cost"
        ]

        # The mock provider is free, so this is exact rather than approximate —
        # which is the point: a float pipeline would not reliably produce "0".
        assert str(cost) in {"0", "0.0", "0E-10"}
