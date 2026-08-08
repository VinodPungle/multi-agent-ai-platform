"""Chat endpoints, wired end to end.

These run the real application: real container, real gateway, real mock
provider, real memory. Nothing is faked, so what they prove is what a browser
would get — including the SSE bytes on the wire, which is the part unit tests
cannot reach.

The mock provider streams with no delay here. The delay exists to make streaming
visible to a human; making a test suite wait for it would buy nothing.
"""

from __future__ import annotations

import json
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
    SearchSettings,
    ServerSettings,
    TelemetrySettings,
)

pytestmark = pytest.mark.integration

CHAT = "/api/v1/chat"

#: The suite runs each test in an empty temporary directory, so the default
#: relative prompts path cannot resolve. Point at the repository's real assets:
#: these tests should fail if a committed prompt is malformed.
PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts"


@pytest.fixture
def chat_settings() -> PlatformSettings:
    """Settings with the mock provider registered and no streaming delay."""
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
        mock_provider=MockProviderSettings(enabled=True, chunk_delay_seconds=0.0),
        agent=AgentSettings(provider_id="mock", model_id="mock-echo"),
        chat=ChatSettings(agent_id="chat-agent", prompts_directory=str(PROMPTS_ROOT)),
    )


@pytest.fixture
def chat_app(chat_settings: PlatformSettings) -> FastAPI:
    return create_app(chat_settings)


@pytest.fixture
def chat_client(chat_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(chat_app) as client:
        yield client


def parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse an SSE response body into (event name, payload) pairs.

    Deliberately a real parser rather than a substring search: it is what
    verifies the framing a browser depends on, and a test that only looked for
    a key in the raw text would pass on a stream no client could read.
    """
    events: list[tuple[str, dict[str, object]]] = []

    for block in body.split("\n\n"):
        if not block.strip() or block.lstrip().startswith(":"):
            continue

        name = ""
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))

        if data_lines:
            events.append((name, json.loads("\n".join(data_lines))))

    return events


class TestSendMessage:
    def test_a_message_gets_an_answer(self, chat_client: TestClient) -> None:
        response = chat_client.post(f"{CHAT}/messages", json={"message": "What is this?"})

        assert response.status_code == 200
        body = response.json()
        assert body["content"]
        assert body["provider_id"] == "mock"
        assert body["model_id"] == "mock-echo"

    def test_a_conversation_id_is_issued_when_none_is_supplied(
        self, chat_client: TestClient
    ) -> None:
        """A client must never have to invent an identifier."""
        response = chat_client.post(f"{CHAT}/messages", json={"message": "hello"})

        assert response.json()["conversation_id"]

    def test_token_usage_is_reported(self, chat_client: TestClient) -> None:
        body = chat_client.post(f"{CHAT}/messages", json={"message": "hello"}).json()

        assert body["prompt_tokens"] > 0
        assert body["completion_tokens"] > 0

    def test_cost_is_not_exposed_to_clients(self, chat_client: TestClient) -> None:
        """Recorded in telemetry for operators; not published to every caller."""
        body = chat_client.post(f"{CHAT}/messages", json={"message": "hello"}).json()

        assert "estimated_cost" not in body
        assert "cost" not in body


class TestValidation:
    def test_an_empty_message_is_rejected(self, chat_client: TestClient) -> None:
        response = chat_client.post(f"{CHAT}/messages", json={"message": ""})

        assert response.status_code == 422
        assert response.json()["error"]["category"] == "validation"

    def test_a_whitespace_only_message_is_rejected(self, chat_client: TestClient) -> None:
        """Passes the length check at the boundary and must still be refused."""
        response = chat_client.post(f"{CHAT}/messages", json={"message": "   "})

        assert response.status_code == 422

    def test_an_oversized_message_is_rejected(self, chat_client: TestClient) -> None:
        response = chat_client.post(f"{CHAT}/messages", json={"message": "x" * 40_000})

        assert response.status_code == 422

    def test_an_unknown_field_is_rejected(self, chat_client: TestClient) -> None:
        """`extra="forbid"`: a typo in a client is a visible error, not a silent no-op."""
        response = chat_client.post(f"{CHAT}/messages", json={"message": "hi", "temperture": 0.5})

        assert response.status_code == 422

    def test_a_malformed_conversation_id_is_rejected(self, chat_client: TestClient) -> None:
        """The id can reach a storage key, so its shape is constrained at the boundary."""
        response = chat_client.post(
            f"{CHAT}/messages", json={"message": "hi", "conversation_id": "../../etc/passwd"}
        )

        assert response.status_code == 422


class TestSessionMemory:
    def test_a_conversation_accumulates_turns(self, chat_client: TestClient) -> None:
        first = chat_client.post(f"{CHAT}/messages", json={"message": "first"}).json()
        conversation_id = first["conversation_id"]

        chat_client.post(
            f"{CHAT}/messages", json={"message": "second", "conversation_id": conversation_id}
        )

        history = chat_client.get(f"{CHAT}/conversations/{conversation_id}").json()
        assert [message["content"] for message in history["messages"]][::2] == [
            "first",
            "second",
        ]

    def test_the_model_sees_earlier_turns(self, chat_client: TestClient) -> None:
        """The mock reports the turn number, which is only knowable from history."""
        first = chat_client.post(f"{CHAT}/messages", json={"message": "first"}).json()
        conversation_id = first["conversation_id"]

        second = chat_client.post(
            f"{CHAT}/messages", json={"message": "second", "conversation_id": conversation_id}
        ).json()

        assert "turn 2" in second["content"]

    def test_conversations_are_isolated(self, chat_client: TestClient) -> None:
        one = chat_client.post(f"{CHAT}/messages", json={"message": "alpha"}).json()
        two = chat_client.post(f"{CHAT}/messages", json={"message": "beta"}).json()

        history = chat_client.get(f"{CHAT}/conversations/{two['conversation_id']}").json()

        assert one["conversation_id"] != two["conversation_id"]
        assert all("alpha" not in message["content"] for message in history["messages"])

    def test_an_unknown_conversation_is_empty_rather_than_missing(
        self, chat_client: TestClient
    ) -> None:
        """A client restoring its view before writing anything is the normal case."""
        response = chat_client.get(f"{CHAT}/conversations/never-seen")

        assert response.status_code == 200
        assert response.json()["messages"] == []

    def test_clearing_forgets_the_conversation(self, chat_client: TestClient) -> None:
        created = chat_client.post(f"{CHAT}/messages", json={"message": "hello"}).json()
        conversation_id = created["conversation_id"]

        deleted = chat_client.delete(f"{CHAT}/conversations/{conversation_id}")

        assert deleted.status_code == 204
        history = chat_client.get(f"{CHAT}/conversations/{conversation_id}").json()
        assert history["messages"] == []

    def test_clearing_an_unknown_conversation_succeeds(self, chat_client: TestClient) -> None:
        assert chat_client.delete(f"{CHAT}/conversations/never-seen").status_code == 204

    def test_memory_does_not_survive_a_restart(self, chat_settings: PlatformSettings) -> None:
        """Session memory by definition. A new process starts with nothing."""
        with TestClient(create_app(chat_settings)) as first_client:
            created = first_client.post(f"{CHAT}/messages", json={"message": "hello"}).json()

        with TestClient(create_app(chat_settings)) as second_client:
            history = second_client.get(f"{CHAT}/conversations/{created['conversation_id']}").json()

        assert history["messages"] == []


class TestStreaming:
    def test_the_response_is_an_sse_stream(self, chat_client: TestClient) -> None:
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "hello"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"

    def test_the_event_sequence_is_started_deltas_completed(self, chat_client: TestClient) -> None:
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "hello"})

        events = parse_sse(response.text)
        names = [name for name, _ in events]

        assert names[0] == "started"
        assert names[-1] == "completed"
        assert "delta" in names

    def test_deltas_reassemble_into_the_completed_content(self, chat_client: TestClient) -> None:
        """The browser appends deltas; if they do not reassemble, it renders nonsense."""
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "hello"})

        events = parse_sse(response.text)
        deltas = "".join(str(payload["delta"]) for name, payload in events if name == "delta")
        completed = next(payload for name, payload in events if name == "completed")

        assert deltas == completed["content"]

    def test_the_started_event_identifies_the_conversation_and_message(
        self, chat_client: TestClient
    ) -> None:
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "hello"})

        _, started = parse_sse(response.text)[0]

        assert started["conversation_id"]
        assert started["message_id"]

    def test_a_streamed_turn_is_stored(self, chat_client: TestClient) -> None:
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "hello"})
        _, started = parse_sse(response.text)[0]

        history = chat_client.get(f"{CHAT}/conversations/{started['conversation_id']}").json()

        assert len(history["messages"]) == 2

    def test_an_invalid_message_fails_before_the_stream_opens(
        self, chat_client: TestClient
    ) -> None:
        """Failing here still allows a proper status code; failing later would not."""
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "   "})

        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/json")

    def test_the_answer_contains_markdown_and_a_code_block(self, chat_client: TestClient) -> None:
        """The renderer and the highlighter both need something real to render."""
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "explain"})

        completed = next(
            payload for name, payload in parse_sse(response.text) if name == "completed"
        )
        content = str(completed["content"])

        assert "## " in content
        assert "```python" in content


class TestRegeneration:
    def test_it_re_answers_without_duplicating_the_question(self, chat_client: TestClient) -> None:
        created = chat_client.post(f"{CHAT}/messages", json={"message": "the question"}).json()
        conversation_id = created["conversation_id"]

        chat_client.post(f"{CHAT}/conversations/{conversation_id}/regenerate")

        history = chat_client.get(f"{CHAT}/conversations/{conversation_id}").json()
        assert [message["content"] for message in history["messages"]].count("the question") == 1

    def test_regenerating_an_empty_conversation_is_rejected(self, chat_client: TestClient) -> None:
        response = chat_client.post(f"{CHAT}/conversations/never-seen/regenerate")

        assert response.status_code == 422


class TestCorrelation:
    def test_a_chat_response_carries_the_correlation_id(self, chat_client: TestClient) -> None:
        response = chat_client.post(
            f"{CHAT}/messages",
            json={"message": "hello"},
            headers={"X-Correlation-ID": "client-supplied-id"},
        )

        assert response.headers["X-Correlation-ID"] == "client-supplied-id"


class TestHealthReflectsRegisteredComponents:
    def test_memory_and_the_provider_are_probed(self, chat_client: TestClient) -> None:
        """`/ready` must report the real system, not just the process."""
        body = chat_client.get("/health").json()

        names = {component["name"] for component in body["report"]["components"]}
        assert "session-memory" in names
        assert "mock" in names


class TestToolVisibility:
    """The client is told when the agent used a tool.

    A searching turn spends a whole model call plus the search before the first
    character of the answer. Without an event in that gap the browser shows a
    blank bubble, which is indistinguishable from a hang — and afterwards, an
    answer that quietly used a search looks identical to one the model invented.
    """

    @pytest.fixture
    def searching_settings(self, chat_settings: PlatformSettings) -> PlatformSettings:
        """Chat settings with search enabled and the agent allowed to use it."""
        return chat_settings.model_copy(
            update={
                "features": chat_settings.features.model_copy(update={"search": True}),
                "search": SearchSettings(provider="mock"),
                "agent": chat_settings.agent.model_copy(update={"tool_ids": ("internet-search",)}),
            }
        )

    @pytest.fixture
    def searching_client(self, searching_settings: PlatformSettings) -> Iterator[TestClient]:
        with TestClient(create_app(searching_settings)) as client:
            yield client

    def test_a_tool_event_precedes_the_answer(self, searching_client: TestClient) -> None:
        response = searching_client.post(
            f"{CHAT}/messages/stream",
            json={"message": "search for the eiffel tower"},
        )

        names = [name for name, _ in parse_sse(response.text)]

        assert "tool" in names
        assert names.index("tool") < names.index("delta")

    def test_the_tool_event_names_the_tool_and_the_query(
        self, searching_client: TestClient
    ) -> None:
        response = searching_client.post(
            f"{CHAT}/messages/stream",
            json={"message": "search for the eiffel tower"},
        )

        tool = next(payload for name, payload in parse_sse(response.text) if name == "tool")

        assert tool["tool_id"] == "internet-search"
        assert "eiffel" in str(tool["summary"]).lower()

    def test_a_turn_without_tools_emits_no_tool_event(self, chat_client: TestClient) -> None:
        """The common path must not acquire a spurious caption."""
        response = chat_client.post(f"{CHAT}/messages/stream", json={"message": "hello"})

        names = [name for name, _ in parse_sse(response.text)]

        assert "tool" not in names

    def test_the_tool_event_does_not_pollute_the_answer(self, searching_client: TestClient) -> None:
        """It carries no text, so deltas must still reassemble exactly."""
        response = searching_client.post(
            f"{CHAT}/messages/stream",
            json={"message": "search for the eiffel tower"},
        )

        events = parse_sse(response.text)
        deltas = "".join(str(payload["delta"]) for name, payload in events if name == "delta")
        completed = next(payload for name, payload in events if name == "completed")

        assert deltas == completed["content"]
