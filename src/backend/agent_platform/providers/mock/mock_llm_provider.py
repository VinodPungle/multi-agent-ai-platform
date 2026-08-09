"""A provider that answers locally, for development and tests.

What it is for
    Exercising every part of the platform that sits *around* a model — the
    gateway's policies, SSE streaming, session memory, the chat UI, error
    handling — without a network call, an API key or a cent of spend.

What it deliberately is not
    An imitation of a language model. Its answers are templated and
    deterministic. Anything downstream that depends on the *content* of a
    response would be depending on a fiction; anything that depends on its
    *shape* is exactly what this exists to test.

The generated answer includes a heading, a list and a fenced code block on
purpose: those are the three things the Markdown renderer and the syntax
highlighter have to get right, and a mock that only ever returned plain prose
would leave both untested until a real model first produced one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Sequence
from decimal import Decimal

from agent_platform.telemetry.logging import get_logger
from agent_platform.tools.internet_search_tool import INTERNET_SEARCH_TOOL_ID
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message, ToolCall
from agent_platform_sdk.dto.model import ModelDescriptor, ModelPricing
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

__all__ = ["MockLLMProvider"]

_logger = get_logger(__name__)

#: What this provider actually does. One definition, read by both `supports()`
#: and `list_models()` — they were maintained separately and disagreed, which is
#: the only way that mistake happens.
_MOCK_CAPABILITIES = frozenset(
    {
        Capability.STREAMING,
        Capability.COST_REPORTING,
        Capability.TOOL_CALLING,
    }
)

#: Characters per token. The real figure depends on the tokeniser, which a mock
#: has no business pretending to have; 4 is the widely used approximation for
#: English text and is documented as an estimate everywhere it surfaces.
_CHARACTERS_PER_TOKEN = 4

_GREETINGS = frozenset({"hi", "hello", "hey", "yo", "good morning", "good evening"})

#: Words that make this mock request a search. A real model decides from the
#: tool's description; a deterministic stand-in needs a rule, and a rule the
#: reader can see beats one hidden in a heuristic.
_SEARCH_TRIGGERS = ("search", "look up", "find out", "latest", "current", "news about")


class MockLLMProvider:
    """Generates deterministic answers without leaving the process.

    Satisfies :class:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider`
    structurally — it inherits nothing, per ADR-0004.

    Deterministic on purpose: the same conversation produces the same answer, so
    a UI test can assert on the rendered output and a streaming test can count
    chunks. A mock with random output would make both flaky.
    """

    def __init__(
        self,
        provider_id: str = "mock",
        model_id: str = "mock-echo",
        chunk_delay_seconds: float = 0.02,
    ) -> None:
        """Create the provider.

        Args:
            provider_id: Identifier it registers under.
            model_id: The single model it serves.
            chunk_delay_seconds: Pause between streamed chunks. Non-zero by
                default because a stream that arrives instantly hides every
                bug that only appears when tokens trickle — a UI that never
                repaints mid-stream, a client that assumes one chunk holds the
                whole answer, a cancel button with nothing to cancel.
        """
        self._provider_id = provider_id
        self._model_id = model_id
        self._chunk_delay_seconds = chunk_delay_seconds

    # -- Provider ----------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    async def initialize(self) -> None:
        """No resources to acquire. Logged so startup shows what was registered."""
        _logger.info(
            "provider.initialized",
            provider_id=self._provider_id,
            model_id=self._model_id,
            detail="Mock provider — responses are generated locally, not by a model.",
        )

    async def health_check(self) -> ComponentHealth:
        """Always healthy: there is no dependency that could be unreachable."""
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail="Mock provider. No external dependency.",
        )

    def supports(self, capability: Capability) -> bool:
        """Declare only what is genuinely implemented.

        Claiming structured output would make the runtime route work here that
        this provider cannot actually do, and the failure would surface far from
        its cause.

        Tool calling *is* implemented — see :meth:`_maybe_tool_call`, which both
        ``generate`` and ``stream`` go through. This method denied it until model
        routing started reading capability declarations and caught the
        disagreement: the claim had simply gone stale when tool calling was
        added, and nothing consumed it in the meantime.
        """
        return capability in _MOCK_CAPABILITIES

    async def close(self) -> None:
        """Nothing to release."""

    # -- Inference ---------------------------------------------------------

    async def generate(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        """Return a complete answer, or a request to call a tool.

        The whole answer is assembled and returned at once; the per-chunk delay
        applies to streaming only.
        """
        del context  # Attribution is the gateway's job; nothing here needs it.

        tool_call = self._maybe_tool_call(request)
        if tool_call is not None:
            # A tool-calling turn: no prose, just the request. The runtime runs
            # the tool and calls back with the result, and `_compose_answer`
            # then produces the grounded reply.
            return CompletionResponse(
                message=Message(role=MessageRole.ASSISTANT, content="", tool_calls=(tool_call,)),
                model_id=request.model_id,
                provider_id=self._provider_id,
                usage=TokenUsage(
                    prompt_tokens=self._estimate_tokens(self._prompt_text(request)),
                    completion_tokens=8,
                ),
                estimated_cost=Decimal(0),
                finish_reason="tool_calls",
                provider_metadata={"simulated": "true"},
                model_metadata={"model": self._model_id, "kind": "mock"},
            )

        content = self._compose_answer(request)
        usage = TokenUsage(
            prompt_tokens=self._estimate_tokens(self._prompt_text(request)),
            completion_tokens=self._estimate_tokens(content),
        )

        return CompletionResponse(
            message=Message(role=MessageRole.ASSISTANT, content=content),
            model_id=request.model_id,
            provider_id=self._provider_id,
            usage=usage,
            estimated_cost=Decimal(0),
            finish_reason="stop",
            provider_metadata={"simulated": "true"},
            model_metadata={"model": self._model_id, "kind": "mock"},
        )

    async def stream(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Emit the answer incrementally, one word at a time.

        Word-level rather than character-level: it is the granularity a real
        tokeniser produces closely enough for a UI to be built against, and it
        keeps chunk counts small enough to assert on in tests.

        Whitespace is attached to the *preceding* word so that concatenating
        every delta reproduces the answer exactly. Consumers rely on that — the
        frontend appends deltas directly to what it has already rendered.

        Tool calls are streamed too, on the terminal chunk, matching what
        ``generate`` does for the same request. A mock that requested tools only
        on the non-streaming path would have made the streaming tool loop
        untestable offline — and it is precisely because the mock never streamed
        a tool call that the streaming path went so long without one.
        """
        del context

        tool_call = self._maybe_tool_call(request)
        if tool_call is not None:
            # No prose on a tool turn, matching `generate`. The terminal chunk
            # carries the request; the loop runs the tool and streams again.
            yield CompletionChunk(
                delta="",
                tool_calls=(tool_call,),
                finish_reason="tool_calls",
                usage=TokenUsage(
                    prompt_tokens=self._estimate_tokens(self._prompt_text(request)),
                    completion_tokens=8,
                ),
            )
            return

        content = self._compose_answer(request)
        words = content.split(" ")

        for index, word in enumerate(words):
            is_last = index == len(words) - 1
            delta = word if is_last else f"{word} "

            if self._chunk_delay_seconds > 0:
                await asyncio.sleep(self._chunk_delay_seconds)

            yield CompletionChunk(delta=delta)

        # Usage and the finish reason arrive on a terminal chunk carrying no
        # text, which is what the OpenAI-style streaming protocol does and what
        # the gateway and the SSE layer are written to expect.
        yield CompletionChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=self._estimate_tokens(self._prompt_text(request)),
                completion_tokens=self._estimate_tokens(content),
            ),
        )

    async def count_tokens(self, request: CompletionRequest) -> TokenUsage:
        """Estimate prompt tokens.

        An approximation, and documented as one: a mock has no tokeniser, and
        inventing a precise-looking number would be worse than an honest
        estimate.
        """
        return TokenUsage(prompt_tokens=self._estimate_tokens(self._prompt_text(request)))

    def estimate_cost(self, model_id: str, usage: TokenUsage) -> Decimal:
        """Return zero. Generating text locally costs nothing.

        Deliberately not a fabricated price. A non-zero mock cost would flow
        into the evaluation and cost-tracking pipelines and make their output
        untrustworthy at exactly the moment someone starts relying on it.
        """
        del model_id, usage
        return Decimal(0)

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        """Return the single model this provider serves."""
        return (
            ModelDescriptor(
                model_id=self._model_id,
                provider_id=self._provider_id,
                display_name="Mock Echo",
                version="1",
                # The same set `supports()` answers from. Two hand-maintained
                # lists is how they drifted apart in the first place.
                capabilities=frozenset(_MOCK_CAPABILITIES),
                max_context_tokens=8192,
                max_output_tokens=2048,
                default_temperature=0.0,
                pricing=ModelPricing(),
                recommended_use_cases=("local development", "integration tests"),
            ),
        )

    # -- Tool calling ------------------------------------------------------

    def _maybe_tool_call(self, request: CompletionRequest) -> ToolCall | None:
        """Decide whether this turn should request a tool.

        Deterministic by design: a mock that chose randomly would make every
        end-to-end tool test flaky. The rule is narrow — the agent must actually
        have the tool, the user's words must ask for a lookup, and no tool result
        may already be present.

        The last condition is what terminates the loop. Without it the mock would
        request the same search forever, and the iteration ceiling would be the
        only thing stopping it.
        """
        if INTERNET_SEARCH_TOOL_ID not in request.tool_ids:
            return None

        if any(message.role is MessageRole.TOOL for message in request.messages):
            return None

        prompt = (self._last_user_message(request.messages) or "").lower()
        if not any(trigger in prompt for trigger in _SEARCH_TRIGGERS):
            return None

        return ToolCall(
            call_id="mock-call-1",
            tool_id=INTERNET_SEARCH_TOOL_ID,
            arguments=json.dumps({"query": self._search_query(prompt), "max_results": 3}),
        )

    @staticmethod
    def _search_query(prompt: str) -> str:
        """Strip the trigger phrase so the query is what was actually asked about.

        Trigger *phrases*, not words. Removing only "search" from "search for the
        eiffel tower" leaves "for the eiffel tower", which matches nothing —
        found by running it against the real API, not by reading the code.
        """
        query = prompt.strip()

        for trigger in _SEARCH_TRIGGERS:
            for phrase in (f"{trigger} for", f"{trigger} about", trigger):
                if query.startswith(phrase):
                    query = query[len(phrase) :]
                    break
            else:
                continue
            break

        cleaned = " ".join(query.split()).strip(" ?.!,")
        return cleaned or prompt.strip(" ?.!,")

    # -- Answer composition ------------------------------------------------

    @staticmethod
    def _prompt_text(request: CompletionRequest) -> str:
        """Return every inbound message as one string, for token estimation."""
        parts: list[str] = []
        if request.system_prompt:
            parts.append(request.system_prompt)
        parts.extend(message.content for message in request.messages)
        return "\n".join(parts)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Approximate a token count from character length."""
        return max(1, len(text) // _CHARACTERS_PER_TOKEN) if text else 0

    def _compose_answer(self, request: CompletionRequest) -> str:
        """Build the answer for ``request``.

        Three shapes, chosen so that a developer exercising the UI sees each of
        them without having to know what to type:

        =================  ==========================================
        Input              Answer
        =================  ==========================================
        No user message    A short explanation of what this provider is
        A greeting         A short conversational reply
        Anything else      Markdown: heading, prose, list, code block
        =================  ==========================================
        """
        tool_results = [message for message in request.messages if message.role is MessageRole.TOOL]
        if tool_results:
            return self._compose_grounded_answer(request, tool_results[-1].content)

        last_user_message = self._last_user_message(request.messages)

        if last_user_message is None:
            return (
                "I did not receive a question. This is the **mock provider** — it generates "
                "replies locally so the platform can be exercised before a real model is "
                "connected in Milestone 05."
            )

        prompt = last_user_message.strip()

        if prompt.lower().rstrip("!.?") in _GREETINGS:
            return (
                f"Hello. You said *{prompt}*.\n\n"
                "I am the mock provider: my answers are templated rather than generated, "
                "so they are the same every time. Ask me anything and I will show you what "
                "a formatted response looks like."
            )

        turn_count = sum(1 for message in request.messages if message.role is MessageRole.USER)

        return (
            f"## Response to your question\n\n"
            f"You asked:\n\n"
            f"> {prompt}\n\n"
            f"This reply came from the **mock provider**, which generates text locally "
            f"instead of calling a model. It is deterministic, so asking the same question "
            f"again produces exactly this answer.\n\n"
            f"What this response demonstrates:\n\n"
            f"- Markdown rendering, including **bold**, *italic* and `inline code`\n"
            f"- Fenced code blocks with syntax highlighting\n"
            f"- Server-sent event streaming, one word at a time\n"
            f"- Session memory — this is turn {turn_count} of the conversation\n\n"
            f"```python\n"
            f"async def generate(request: CompletionRequest) -> CompletionResponse:\n"
            f'    """Every provider implements the same contract."""\n'
            f"    return CompletionResponse(\n"
            f"        message=Message(role=MessageRole.ASSISTANT, content=...),\n"
            f"        model_id=request.model_id,\n"
            f"        provider_id='mock',\n"
            f"    )\n"
            f"```\n\n"
            f"Swapping this provider for Azure AI Foundry changes configuration only — "
            f"no caller of the LLM Gateway is aware of which provider answered."
        )

    def _compose_grounded_answer(self, request: CompletionRequest, tool_output: str) -> str:
        """Answer using what the tool returned.

        Cites every result. A grounded answer whose sources the reader cannot
        check is indistinguishable from an ungrounded one, which is the failure
        mode search exists to remove.
        """
        try:
            payload = json.loads(tool_output)
            results = payload.get("results") or []
        except (json.JSONDecodeError, AttributeError):
            results = []

        question = self._last_user_message(request.messages) or "your question"

        if not results:
            return (
                f"I searched for information about *{question}* and found nothing usable. "
                "The mock provider generated this reply; the search itself ran through the "
                "real tool pipeline."
            )

        citations = "\n".join(
            f"{index + 1}. [{result.get('title', 'Untitled')}]({result.get('url', '')})"
            f" — {result.get('snippet', '')}"
            for index, result in enumerate(results)
        )

        return (
            f"## What the search found\n\n"
            f"You asked about *{question}*. I called the **internet-search** tool through "
            f"the runtime's tool pipeline and it returned {len(results)} result(s):\n\n"
            f"{citations}\n\n"
            f"This answer was composed by the mock provider, but the search was real: the "
            f"runtime resolved the tool, enforced its timeout and retry policy, and returned "
            f"the results as a structured `ToolResult`."
        )

    @staticmethod
    def _last_user_message(messages: Sequence[Message]) -> str | None:
        """Return the most recent user message, or ``None`` if there is none."""
        for message in reversed(messages):
            if message.role is MessageRole.USER:
                return message.content
        return None
