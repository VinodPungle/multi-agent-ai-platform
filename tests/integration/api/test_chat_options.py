"""Per-request generation options, and the conversation history list.

The options are a caller's *preferences*, not instructions the runtime is bound
by — so the tests worth having are the ones that prove the platform still says
no: an unknown model is refused rather than substituted, and a value outside the
accepted range never reaches a provider.
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
def chat_client() -> Iterator[TestClient]:
    settings = PlatformSettings(
        app=AppSettings(
            name="test-platform",
            version="0.0.0-test",
            environment=Environment.TESTING,
            debug=True,
        ),
        logging=LoggingSettings(level="WARNING", renderer="json"),
        telemetry=TelemetrySettings(enabled=False),
        mock_provider=MockProviderSettings(enabled=True, chunk_delay_seconds=0.0),
        agent=AgentSettings(provider_id="mock", model_id="mock-echo"),
        chat=ChatSettings(agent_id="chat-agent", prompts_directory=str(PROMPTS_ROOT)),
    )
    app: FastAPI = create_app(settings)
    with TestClient(app) as client:
        yield client


class TestGenerationOptions:
    def test_a_turn_without_options_uses_the_agents_configuration(
        self,
        chat_client: TestClient,
    ) -> None:
        response = chat_client.post("/api/v1/chat/messages", json={"message": "hello"})

        assert response.status_code == 200
        assert response.json()["model_id"] == "mock-echo"

    def test_a_model_can_be_pinned_for_one_turn(self, chat_client: TestClient) -> None:
        response = chat_client.post(
            "/api/v1/chat/messages",
            json={"message": "hello", "model_id": "mock-echo"},
        )

        assert response.json()["model_id"] == "mock-echo"

    def test_an_unknown_model_is_refused_rather_than_substituted(
        self,
        chat_client: TestClient,
    ) -> None:
        """Answering with a different model than asked for is the worse failure."""
        response = chat_client.post(
            "/api/v1/chat/messages",
            json={"message": "hello", "model_id": "no-such-model"},
        )

        assert response.status_code == 404
        assert "pinned-model" in response.json()["error"]["message"]

    def test_zero_temperature_is_accepted_as_a_value(self, chat_client: TestClient) -> None:
        """Not treated as absent: zero is a deliberate request for determinism."""
        response = chat_client.post(
            "/api/v1/chat/messages",
            json={"message": "hello", "temperature": 0},
        )

        assert response.status_code == 200

    def test_a_temperature_outside_the_range_is_rejected(self, chat_client: TestClient) -> None:
        response = chat_client.post(
            "/api/v1/chat/messages",
            json={"message": "hello", "temperature": 5},
        )

        assert response.status_code == 422

    def test_an_unbounded_output_cap_is_rejected(self, chat_client: TestClient) -> None:
        """An unbounded value from an HTTP caller is a bill anyone can write."""
        response = chat_client.post(
            "/api/v1/chat/messages",
            json={"message": "hello", "max_output_tokens": 10_000_000},
        )

        assert response.status_code == 422

    def test_options_apply_to_streaming_too(self, chat_client: TestClient) -> None:
        """`send` and `stream` prepare through one path so they cannot diverge."""
        with chat_client.stream(
            "POST",
            "/api/v1/chat/messages/stream",
            json={"message": "hello", "model_id": "mock-echo", "temperature": 0},
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        assert "mock-echo" in body


class TestConversationHistory:
    def test_it_is_empty_before_anything_is_said(self, chat_client: TestClient) -> None:
        response = chat_client.get("/api/v1/chat/conversations")

        assert response.status_code == 200
        assert response.json()["conversations"] == []

    def test_a_conversation_appears_after_a_turn(self, chat_client: TestClient) -> None:
        chat_client.post("/api/v1/chat/messages", json={"message": "how do budgets work"})

        conversations = chat_client.get("/api/v1/chat/conversations").json()["conversations"]

        assert len(conversations) == 1
        assert conversations[0]["message_count"] == 2

    def test_the_preview_is_how_the_conversation_started(
        self,
        chat_client: TestClient,
    ) -> None:
        """A list is scanned to find something again, and people remember openings."""
        first = chat_client.post(
            "/api/v1/chat/messages",
            json={"message": "how do budgets work"},
        ).json()
        chat_client.post(
            "/api/v1/chat/messages",
            json={"message": "and what about retries", "conversation_id": first["conversation_id"]},
        )

        (conversation,) = chat_client.get("/api/v1/chat/conversations").json()["conversations"]

        assert conversation["preview"] == "how do budgets work"

    def test_the_most_recent_conversation_is_listed_first(
        self,
        chat_client: TestClient,
    ) -> None:
        chat_client.post("/api/v1/chat/messages", json={"message": "older"})
        chat_client.post("/api/v1/chat/messages", json={"message": "newer"})

        conversations = chat_client.get("/api/v1/chat/conversations").json()["conversations"]

        assert conversations[0]["preview"] == "newer"

    def test_the_limit_is_bounded(self, chat_client: TestClient) -> None:
        assert chat_client.get("/api/v1/chat/conversations?limit=0").status_code == 422
        assert chat_client.get("/api/v1/chat/conversations?limit=999").status_code == 422

    def test_a_listed_conversation_can_be_reopened(self, chat_client: TestClient) -> None:
        """The whole point of the list: an entry has to lead back to a transcript."""
        chat_client.post("/api/v1/chat/messages", json={"message": "how do budgets work"})
        (conversation,) = chat_client.get("/api/v1/chat/conversations").json()["conversations"]

        transcript = chat_client.get(
            f"/api/v1/chat/conversations/{conversation['conversation_id']}"
        ).json()

        assert transcript["messages"][0]["content"] == "how do budgets work"
