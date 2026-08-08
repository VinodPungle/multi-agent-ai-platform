"""The general conversational agent.

The first agent, and the reference for every agent that follows. Note how little
it does: render a prompt, assemble messages, call the gateway, translate the
answer. That is the whole of an agent's job.

Everything it does *not* do is the point. It does not load memory, choose a
model, resolve a prompt version, retry, time out, publish events, or know which
provider exists — the runtime and the gateway own all of that. An agent that
picked up any one of those responsibilities would do it once per agent, and the
second agent would do it slightly differently.

Small enough to read in one sitting, deliberately: `CLAUDE.md` warns against
"God Agents", and they begin with a single convenience added here rather than in
the runtime.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from agent_platform.prompts.renderer import render_prompt
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.dto.completion import CompletionChunk, CompletionRequest
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.types.enums import MessageRole

__all__ = ["ChatAgent"]

_logger = get_logger(__name__)


class ChatAgent:
    """Answers a conversational turn.

    Satisfies :class:`~agent_platform_sdk.interfaces.agent.Agent` structurally —
    it inherits nothing, per ADR-0004.
    """

    def __init__(self, descriptor: AgentDescriptor, gateway: LLMGateway) -> None:
        """Create the agent.

        Args:
            descriptor: Declarative definition. What this agent *is* — its
                model, prompt, tools and budget — is data the runtime reads,
                not a property of this class.
            gateway: Provider-independent access to inference. The gateway, not
                a provider: this agent cannot name one.
        """
        self._descriptor = descriptor
        self._gateway = gateway

    @property
    def descriptor(self) -> AgentDescriptor:
        """Declarative definition of this agent."""
        return self._descriptor

    async def execute(self, request: AgentRequest, context: ExecutionContext) -> AgentResult:
        """Produce a complete response."""
        completion = self._build_completion(request)
        response = await self._gateway.generate(completion, context)

        # `agent_id` is not passed explicitly: the runtime stamps it on the
        # context, and `to_log_fields()` already carries it. Supplying both
        # raises a duplicate-keyword TypeError inside the logger.
        _logger.debug(
            "agent.completed",
            completion_characters=len(response.message.content),
            **context.to_log_fields(),
        )

        return AgentResult(
            message=response.message,
            agent_id=self._descriptor.agent_id,
            model_id=response.model_id,
            provider_id=response.provider_id,
            usage=response.usage,
            estimated_cost=response.estimated_cost,
            latency_ms=response.latency_ms,
            finish_reason=response.finish_reason,
            model_calls=1,
        )

    async def stream(
        self,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Produce a response incrementally.

        Yields the gateway's chunks unchanged. Re-wrapping them in an
        agent-specific type would mean translating the same data twice — once
        here and once at the API boundary — for no gain.
        """
        async for chunk in self._gateway.stream(self._build_completion(request), context):
            yield chunk

    def _build_completion(self, request: AgentRequest) -> CompletionRequest:
        """Assemble the model request.

        Deterministic and side-effect free, which is what makes it testable
        without a gateway (``architecture.md``, "Context Assembly").

        The system prompt travels in ``system_prompt`` rather than as a leading
        message, so each provider adapter places it where its API expects and it
        is never stored in history as if a participant had said it.
        """
        system_prompt = render_prompt(request.prompt, request.variables) if request.prompt else None

        return CompletionRequest(
            model_id=request.model_id,
            # history → the user's message → the tool exchange. Order is the
            # whole point: a tool result before the question it answers reads to
            # a model as evidence for something nobody asked.
            messages=(
                *request.history,
                Message(role=MessageRole.USER, content=request.input),
                *request.tool_exchange,
            ),
            system_prompt=system_prompt,
            # The descriptor's values are the fallback, not the override: a
            # per-request value is a deliberate caller decision and must win.
            temperature=(
                request.temperature
                if request.temperature is not None
                else self._descriptor.temperature
            ),
            max_output_tokens=(
                request.max_output_tokens
                if request.max_output_tokens is not None
                else self._descriptor.max_output_tokens
            ),
            tool_ids=self._descriptor.tool_ids,
            metadata={"agent_id": self._descriptor.agent_id},
        )
