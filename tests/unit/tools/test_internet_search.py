"""Internet search: providers, the tool, and the loop end to end.

Three layers, tested where each actually fails:

* **Providers** — parsing. The DuckDuckGo payload is mined defensively, so the
  tests feed it shapes a live API will eventually produce: missing fields,
  grouped topics, an empty response.
* **The tool** — argument validation and the success/failure boundary. "No
  results" is a success; a provider outage is a failure the agent can read.
* **The loop** — the whole thing, driven by the mock model that really does
  request a tool.

One test hits the live API. It is marked `integration` so it can be excluded,
and it asserts only on the *shape* of what comes back — asserting on live web
content would produce a test that fails whenever the web changes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent_platform.exceptions.base import ProviderError, ValidationError
from agent_platform.search.duckduckgo_search_provider import DuckDuckGoSearchProvider
from agent_platform.search.mock_search_provider import MockSearchProvider
from agent_platform.tools.internet_search_tool import (
    INTERNET_SEARCH_TOOL_ID,
    InternetSearchTool,
)
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.search import SearchQuery, SearchResults
from agent_platform_sdk.dto.tool import ToolInvocation
from agent_platform_sdk.interfaces.search_provider import SearchProvider
from agent_platform_sdk.interfaces.tool_provider import ToolProvider

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


def a_payload(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401 - arbitrary API payload
    """Build a DuckDuckGo Instant Answer payload."""
    payload: dict[str, Any] = {
        "Heading": "Eiffel Tower",
        "AbstractText": "A wrought-iron lattice tower in Paris.",
        "AbstractURL": "https://en.wikipedia.org/wiki/Eiffel_Tower",
        "RelatedTopics": [
            {"FirstURL": "https://example.com/a", "Text": "Topic A - about A"},
            {"FirstURL": "https://example.com/b", "Text": "Topic B - about B"},
        ],
    }
    payload.update(overrides)
    return payload


def a_client(payload: dict[str, Any], status: int = 200) -> httpx.AsyncClient:
    """Build a client that answers with ``payload`` without touching the network."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestProviderContracts:
    @pytest.mark.parametrize(
        "factory",
        [MockSearchProvider, DuckDuckGoSearchProvider],
        ids=["mock", "duckduckgo"],
    )
    def test_every_provider_satisfies_the_contract(
        self, factory: Callable[[], SearchProvider]
    ) -> None:
        assert isinstance(factory(), SearchProvider)

    def test_the_mock_does_not_claim_citations(self) -> None:
        """Its URLs do not resolve. Claiming otherwise would produce fake citations."""
        assert MockSearchProvider().supports_citations is False

    def test_duckduckgo_claims_citations(self) -> None:
        assert DuckDuckGoSearchProvider().supports_citations is True


class TestMockSearchProvider:
    async def test_it_returns_results_without_a_network_call(self) -> None:
        provider = MockSearchProvider()

        results = await provider.search(SearchQuery(query="anything"), CONTEXT)

        assert results.results
        assert results.provider_id == "mock-search"

    async def test_it_is_deterministic(self) -> None:
        provider = MockSearchProvider()

        first = await provider.search(SearchQuery(query="same"), CONTEXT)
        second = await provider.search(SearchQuery(query="same"), CONTEXT)

        assert first.results == second.results

    async def test_it_respects_the_result_limit(self) -> None:
        provider = MockSearchProvider()

        results = await provider.search(SearchQuery(query="x", max_results=1), CONTEXT)

        assert len(results.results) == 1


class TestDuckDuckGoParsing:
    """The payload is mined defensively; these are the shapes that arrive."""

    async def test_the_abstract_becomes_the_first_result(self) -> None:
        provider = DuckDuckGoSearchProvider(client=a_client(a_payload()))
        await provider.initialize()

        results = await provider.search(SearchQuery(query="eiffel tower"), CONTEXT)

        assert results.results[0].title == "Eiffel Tower"
        assert results.results[0].url.endswith("Eiffel_Tower")

    async def test_related_topics_become_results(self) -> None:
        provider = DuckDuckGoSearchProvider(client=a_client(a_payload()))
        await provider.initialize()

        results = await provider.search(SearchQuery(query="x"), CONTEXT)

        assert len(results.results) == 3

    async def test_the_title_and_snippet_are_split(self) -> None:
        provider = DuckDuckGoSearchProvider(client=a_client(a_payload()))
        await provider.initialize()

        results = await provider.search(SearchQuery(query="x"), CONTEXT)

        topic = results.results[1]
        assert topic.title == "Topic A"
        assert topic.snippet == "about A"

    async def test_a_payload_with_no_abstract_still_yields_results(self) -> None:
        provider = DuckDuckGoSearchProvider(
            client=a_client(a_payload(AbstractText="", AbstractURL=""))
        )
        await provider.initialize()

        results = await provider.search(SearchQuery(query="x"), CONTEXT)

        assert len(results.results) == 2

    async def test_a_grouped_topic_without_a_url_is_skipped(self) -> None:
        """Grouped topics are disambiguations, which make poor evidence."""
        provider = DuckDuckGoSearchProvider(
            client=a_client(
                a_payload(RelatedTopics=[{"Name": "Group", "Topics": [{"FirstURL": "x"}]}])
            )
        )
        await provider.initialize()

        results = await provider.search(SearchQuery(query="x"), CONTEXT)

        assert len(results.results) == 1

    async def test_an_empty_payload_is_empty_results_not_an_error(self) -> None:
        """Nothing found is an answer the agent should reason about."""
        provider = DuckDuckGoSearchProvider(client=a_client({}))
        await provider.initialize()

        results = await provider.search(SearchQuery(query="x"), CONTEXT)

        assert results.results == ()

    async def test_the_result_limit_is_respected(self) -> None:
        provider = DuckDuckGoSearchProvider(client=a_client(a_payload()))
        await provider.initialize()

        results = await provider.search(SearchQuery(query="x", max_results=2), CONTEXT)

        assert len(results.results) == 2

    async def test_an_http_failure_raises_a_provider_error(self) -> None:
        provider = DuckDuckGoSearchProvider(client=a_client({}, status=503))
        await provider.initialize()

        with pytest.raises(ProviderError):
            await provider.search(SearchQuery(query="x"), CONTEXT)

    async def test_the_error_does_not_leak_the_request(self) -> None:
        """Exception text can carry the full URL and headers."""
        provider = DuckDuckGoSearchProvider(client=a_client({}, status=503))
        await provider.initialize()

        with pytest.raises(ProviderError) as raised:
            await provider.search(SearchQuery(query="secret-query"), CONTEXT)

        assert "secret-query" not in raised.value.message

    async def test_searching_before_initialisation_is_refused(self) -> None:
        provider = DuckDuckGoSearchProvider()

        with pytest.raises(ProviderError, match="not initialised"):
            await provider.search(SearchQuery(query="x"), CONTEXT)


class TestInternetSearchTool:
    def build(self, provider: SearchProvider | None = None) -> InternetSearchTool:
        return InternetSearchTool(provider or MockSearchProvider())

    def test_it_satisfies_the_tool_contract(self) -> None:
        assert isinstance(self.build(), ToolProvider)

    def test_the_descriptor_declares_a_schema_a_model_can_follow(self) -> None:
        descriptor = self.build().descriptor

        assert descriptor.tool_id == INTERNET_SEARCH_TOOL_ID
        assert descriptor.input_schema["required"] == ["query"]
        assert "query" in descriptor.input_schema["properties"]

    def test_the_description_says_when_not_to_use_it(self) -> None:
        """It is prompt material: a vague description produces a model that searches everything."""
        assert "Do not use it" in self.build().descriptor.description

    async def test_a_valid_invocation_passes_validation(self) -> None:
        await self.build().validate(
            ToolInvocation(tool_id=INTERNET_SEARCH_TOOL_ID, arguments={"query": "x"})
        )

    @pytest.mark.parametrize(
        "arguments",
        [{}, {"query": ""}, {"query": "   "}, {"query": 42}, {"query": "x" * 401}],
    )
    async def test_invalid_arguments_are_rejected(self, arguments: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            await self.build().validate(
                ToolInvocation(tool_id=INTERNET_SEARCH_TOOL_ID, arguments=arguments)
            )

    @pytest.mark.parametrize("max_results", [0, 11, "three", True])
    async def test_an_invalid_result_count_is_rejected(self, max_results: object) -> None:
        with pytest.raises(ValidationError):
            await self.build().validate(
                ToolInvocation(
                    tool_id=INTERNET_SEARCH_TOOL_ID,
                    arguments={"query": "x", "max_results": max_results},
                )
            )

    async def test_a_search_returns_structured_results(self) -> None:
        result = await self.build().execute(
            ToolInvocation(tool_id=INTERNET_SEARCH_TOOL_ID, arguments={"query": "x"}), CONTEXT
        )

        assert result.succeeded is True
        assert result.output is not None
        assert result.output["result_count"] > 0
        assert {"title", "url", "snippet"} == set(result.output["results"][0])

    async def test_only_citable_fields_reach_the_model(self) -> None:
        """Scores and timestamps would be spent context for no benefit."""
        result = await self.build().execute(
            ToolInvocation(tool_id=INTERNET_SEARCH_TOOL_ID, arguments={"query": "x"}), CONTEXT
        )

        assert result.output is not None
        assert "score" not in result.output["results"][0]

    async def test_a_provider_outage_is_a_failed_result_not_an_exception(self) -> None:
        """An agent that knows its tool is down can say so; an exception aborts the turn."""

        class BrokenProvider(MockSearchProvider):
            async def search(self, query: SearchQuery, context: ExecutionContext) -> SearchResults:
                message = "search backend unreachable"
                raise ProviderError(message)

        result = await self.build(BrokenProvider()).execute(
            ToolInvocation(tool_id=INTERNET_SEARCH_TOOL_ID, arguments={"query": "x"}), CONTEXT
        )

        assert result.succeeded is False
        assert result.error_message == "search backend unreachable"


class TestToolLoopEndToEnd:
    """The mock model really does request the tool, so the loop runs for real."""

    async def test_a_search_request_triggers_the_tool_and_a_grounded_answer(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack(with_tools=True)

        turn = await stack.runtime.prepare(
            "chat-agent", "search for the eiffel tower", CONTEXT, "c1"
        )
        result = await stack.runtime.execute(turn)

        assert result.tool_invocations == 1
        assert result.model_calls == 2
        assert "What the search found" in result.message.content

    async def test_the_answer_cites_its_sources(self, build_stack: Callable[..., Any]) -> None:
        stack = build_stack(with_tools=True)

        turn = await stack.runtime.prepare("chat-agent", "search for python", CONTEXT, "c1")
        result = await stack.runtime.execute(turn)

        assert "https://example.invalid/search/1" in result.message.content

    async def test_an_ordinary_question_costs_one_model_call(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """A tool that fires on everything is a tool that doubles every bill."""
        stack = build_stack(with_tools=True)

        turn = await stack.runtime.prepare("chat-agent", "what is 2 + 2?", CONTEXT, "c1")
        result = await stack.runtime.execute(turn)

        assert result.tool_invocations == 0
        assert result.model_calls == 1

    async def test_an_agent_without_tools_never_calls_one(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack(with_tools=False)

        turn = await stack.runtime.prepare("chat-agent", "search for anything", CONTEXT, "c1")
        result = await stack.runtime.execute(turn)

        assert result.tool_invocations == 0

    async def test_the_tool_exchange_is_not_stored_in_memory(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """History is the conversation. Tool traffic is execution detail."""
        stack = build_stack(with_tools=True)

        turn = await stack.runtime.prepare("chat-agent", "search for x", CONTEXT, "c1")
        await stack.runtime.execute(turn)

        stored = await stack.memory.load("c1", CONTEXT)
        assert [message.role.value for message in stored] == ["user", "assistant"]

    async def test_a_failing_tool_still_produces_an_answer(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """The agent is told the tool failed and answers anyway."""
        stack = build_stack(with_tools=True, search_fails=True)

        turn = await stack.runtime.prepare("chat-agent", "search for x", CONTEXT, "c1")
        result = await stack.runtime.execute(turn)

        assert result.message.content
        assert result.tool_invocations == 1


class TestToolLoopBounds:
    """The loop is where a runaway model becomes a runaway bill.

    Driven by a stub agent that *always* asks for a tool, because that is the
    failure being guarded against and no well-behaved provider produces it. The
    mock provider deliberately stops after one call, so it cannot exercise these
    paths at all.
    """

    def an_agent(self, **budget: Any) -> Any:  # noqa: ANN401 - forwards to BudgetPolicy
        from agent_platform_sdk.dto.agent import AgentDescriptor
        from agent_platform_sdk.dto.execution import AgentResult
        from agent_platform_sdk.dto.message import Message, ToolCall
        from agent_platform_sdk.policies.budget import BudgetPolicy
        from agent_platform_sdk.types.enums import MessageRole

        class InsatiableAgent:
            """Requests a tool on every turn, forever."""

            def __init__(self) -> None:
                self.calls = 0

            @property
            def descriptor(self) -> AgentDescriptor:
                return AgentDescriptor(
                    agent_id="insatiable",
                    name="Insatiable",
                    description="Always asks for a tool.",
                    provider_id="fake",
                    model_id="test-model",
                    prompt_id="p",
                    tool_ids=(INTERNET_SEARCH_TOOL_ID,),
                    budget=BudgetPolicy(**budget),
                )

            async def execute(self, request: Any, context: Any) -> AgentResult:  # noqa: ANN401
                del request, context
                self.calls += 1
                return AgentResult(
                    message=Message(
                        role=MessageRole.ASSISTANT,
                        content="",
                        tool_calls=(
                            ToolCall(
                                call_id=f"call-{self.calls}",
                                tool_id=INTERNET_SEARCH_TOOL_ID,
                                arguments=json.dumps({"query": "again"}),
                            ),
                        ),
                    ),
                    agent_id="insatiable",
                    model_id="test-model",
                    provider_id="fake",
                )

            def stream(self, request: Any, context: Any) -> Any:  # noqa: ANN401
                raise NotImplementedError

        return InsatiableAgent()

    def an_executor(self) -> Any:  # noqa: ANN401 - a local assembly
        from datetime import UTC, datetime

        from agent_platform.events.publisher import LoggingEventPublisher
        from agent_platform.registries import KeyedRegistry
        from agent_platform.tools.tool_executor import ToolExecutor

        class _Clock:
            def now(self) -> datetime:
                return datetime(2026, 1, 1, tzinfo=UTC)

            def monotonic(self) -> float:
                return 0.0

        registry: KeyedRegistry[ToolProvider] = KeyedRegistry("tool")
        tool = InternetSearchTool(MockSearchProvider())
        registry.register(tool.descriptor.tool_id, tool)
        return ToolExecutor(tools=registry, events=LoggingEventPublisher(), clock=_Clock())

    async def test_the_model_call_ceiling_stops_the_loop(self) -> None:
        from agent_platform.workflow.tool_loop import run_tool_loop
        from agent_platform_sdk.dto.execution import AgentRequest

        agent = self.an_agent(max_model_calls=3)

        result = await run_tool_loop(
            agent,
            AgentRequest(input="go", model_id="test-model"),
            CONTEXT,
            self.an_executor(),
        )

        assert agent.calls == 3
        assert result.model_calls == 3

    async def test_an_exhausted_loop_still_answers(self) -> None:
        """Its last message is a tool request, so returning it would show a blank reply."""
        from agent_platform.workflow.tool_loop import run_tool_loop
        from agent_platform_sdk.dto.execution import AgentRequest

        result = await run_tool_loop(
            self.an_agent(max_model_calls=2),
            AgentRequest(input="go", model_id="test-model"),
            CONTEXT,
            self.an_executor(),
        )

        assert result.message.content
        assert not result.message.tool_calls
        assert result.finish_reason == "tool_limit"

    async def test_the_tool_budget_stops_calls_before_they_are_made(self) -> None:
        """Enforced between iterations, where stopping still saves the next call."""
        from agent_platform.workflow.tool_loop import run_tool_loop
        from agent_platform_sdk.dto.execution import AgentRequest

        result = await run_tool_loop(
            self.an_agent(max_model_calls=4, max_tool_invocations=1),
            AgentRequest(input="go", model_id="test-model"),
            CONTEXT,
            self.an_executor(),
        )

        assert result.tool_invocations == 1

    async def test_a_default_ceiling_applies_without_a_budget(self) -> None:
        """An unbounded loop turns one request into an open-ended bill."""
        from agent_platform.workflow.tool_loop import DEFAULT_MAX_ITERATIONS, run_tool_loop
        from agent_platform_sdk.dto.execution import AgentRequest

        agent = self.an_agent()

        await run_tool_loop(
            agent, AgentRequest(input="go", model_id="test-model"), CONTEXT, self.an_executor()
        )

        assert agent.calls == DEFAULT_MAX_ITERATIONS


@pytest.mark.integration
class TestLiveSearch:
    """One test against the real API.

    Asserts on shape, never on content: the web changes, and a test that asserted
    on what DuckDuckGo says about the Eiffel Tower would be quarantined within a
    week and then ignored.
    """

    async def test_a_real_search_returns_citable_results(self) -> None:
        provider = DuckDuckGoSearchProvider(timeout_seconds=20.0)
        await provider.initialize()

        try:
            results = await provider.search(
                SearchQuery(query="eiffel tower", max_results=3), CONTEXT
            )
        except ProviderError:
            pytest.skip("DuckDuckGo was unreachable; this test needs network access.")
        finally:
            await provider.close()

        assert results.provider_id == "duckduckgo"
        assert results.results, "The Instant Answer API returned nothing for a well-known topic."
        for result in results.results:
            assert result.url.startswith("http")
            assert result.title

    async def test_the_tool_pipeline_works_against_the_real_provider(self) -> None:
        provider = DuckDuckGoSearchProvider(timeout_seconds=20.0)
        await provider.initialize()
        tool = InternetSearchTool(provider)

        try:
            result = await tool.execute(
                ToolInvocation(
                    tool_id=INTERNET_SEARCH_TOOL_ID, arguments={"query": "python programming"}
                ),
                CONTEXT,
            )
        finally:
            await provider.close()

        if not result.succeeded:
            pytest.skip("DuckDuckGo was unreachable; this test needs network access.")

        assert result.output is not None
        assert json.dumps(result.output)  # the payload must be JSON-serialisable for the model
