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
from collections.abc import AsyncGenerator, Sequence
from decimal import Decimal

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.model import ModelDescriptor, ModelPricing
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

__all__ = ["MockLLMProvider"]

_logger = get_logger(__name__)

#: Characters per token. The real figure depends on the tokeniser, which a mock
#: has no business pretending to have; 4 is the widely used approximation for
#: English text and is documented as an estimate everywhere it surfaces.
_CHARACTERS_PER_TOKEN = 4

_GREETINGS = frozenset({"hi", "hello", "hey", "yo", "good morning", "good evening"})


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

        Claiming tool calling or structured output would make the runtime route
        work here that this provider cannot actually do, and the failure would
        surface far from its cause.
        """
        return capability in {Capability.STREAMING, Capability.COST_REPORTING}

    async def close(self) -> None:
        """Nothing to release."""

    # -- Inference ---------------------------------------------------------

    async def generate(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        """Return a complete answer.

        The whole answer is assembled and returned at once; the per-chunk delay
        applies to streaming only.
        """
        del context  # Attribution is the gateway's job; nothing here needs it.

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
        """
        del context

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
                capabilities=frozenset({Capability.STREAMING}),
                max_context_tokens=8192,
                max_output_tokens=2048,
                default_temperature=0.0,
                pricing=ModelPricing(),
                recommended_use_cases=("local development", "integration tests"),
            ),
        )

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

    @staticmethod
    def _last_user_message(messages: Sequence[Message]) -> str | None:
        """Return the most recent user message, or ``None`` if there is none."""
        for message in reversed(messages):
            if message.role is MessageRole.USER:
                return message.content
        return None
