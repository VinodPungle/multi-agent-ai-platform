"""The tool-calling loop.

    model asks for tools → tools run → results go back → model answers

Shared by both workflow engines rather than written twice. The engines differ in
*how* they orchestrate — a compiled graph versus a direct call — and that
difference is real; the loop itself is one algorithm, and two copies of it would
be two places for an off-by-one in the iteration bound.

The LangGraph engine calls this from its agent node today. When the graph grows,
the loop becomes nodes and edges — `agent → should_call_tools? → tools → agent` —
and this module shrinks to the direct engine's use of it. That is a refactor
inside the workflow package, invisible to the runtime and to every agent.

Where budget enforcement finally became real
    Milestone 03 could only report a breach after the fact, because a
    single-call agent has spent everything by the time you can count it. A loop
    changes that: `max_tool_invocations` and `max_model_calls` are checked
    *between* iterations, where stopping still saves the next call. This is the
    seam `_enforce_pre_execution_budget` was left for.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from agent_platform.telemetry.logging import get_logger
from agent_platform.tools.tool_executor import ToolExecutor
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionChunk, TokenUsage
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.dto.message import Message, ToolCall
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.types.enums import MessageRole

__all__ = ["DEFAULT_MAX_ITERATIONS", "run_tool_loop", "stream_tool_loop"]

_logger = get_logger(__name__)

#: Hard ceiling on model calls in one turn, applied when an agent declares no
#: budget of its own. A model that keeps requesting tools without concluding is
#: the classic runaway-cost failure, and an unbounded loop turns one request into
#: an open-ended bill.
DEFAULT_MAX_ITERATIONS = 5


async def run_tool_loop(
    agent: Agent,
    request: AgentRequest,
    context: ExecutionContext,
    executor: ToolExecutor | None,
) -> AgentResult:
    """Run ``agent`` until it answers without asking for a tool.

    Args:
        agent: The agent to run.
        request: The prepared request.
        context: Execution context, for attribution.
        executor: Tool execution pipeline. ``None`` disables tool calling
            entirely — which is what the search feature flag being off means, and
            why a disabled flag costs exactly one model call.

    Returns:
        The final result. ``model_calls`` and ``tool_invocations`` count the
        whole loop, not the last iteration, so budgets and cost attribution see
        what the turn actually spent.
    """
    permitted = agent.descriptor.tool_ids

    # No executor, or an agent that declares no tools: one call, no loop, no
    # behaviour change from Milestone 03.
    if executor is None or not permitted:
        return await agent.execute(request, context)

    budget = agent.descriptor.budget
    max_iterations = budget.max_model_calls or DEFAULT_MAX_ITERATIONS
    max_tool_calls = budget.max_tool_invocations
    declarations = _declarations(executor, permitted)

    exchange: tuple[Message, ...] = ()
    model_calls = 0
    tool_invocations = 0
    result: AgentResult | None = None

    while model_calls < max_iterations:
        result = await agent.execute(
            request.model_copy(update={"tool_exchange": exchange, "tools": declarations}),
            context,
        )
        model_calls += 1

        calls = result.message.tool_calls
        if not calls:
            break

        if max_tool_calls is not None and tool_invocations + len(calls) > max_tool_calls:
            # Stopping *before* the calls, not after: this is the point where
            # enforcement still saves something. The model is told, so it can
            # answer with what it already has.
            _logger.warning(
                "runtime.tool_budget_exceeded",
                agent_id=agent.descriptor.agent_id,
                requested=len(calls),
                already_used=tool_invocations,
                limit=max_tool_calls,
                **context.to_log_fields(),
            )
            exchange = (
                *exchange,
                result.message,
                *(
                    _tool_message(
                        call,
                        ToolResult(
                            tool_id=call.tool_id,
                            call_id=call.call_id,
                            succeeded=False,
                            error_message=(
                                "This turn's tool budget is exhausted. "
                                "Answer with the information you already have."
                            ),
                        ),
                    )
                    for call in calls
                ),
            )
            continue

        results = [await _invoke(executor, call, context, permitted) for call in calls]
        tool_invocations += len(results)

        exchange = (
            *exchange,
            # The assistant's own request has to be replayed, or the tool
            # results that follow answer a question the transcript never asked.
            result.message,
            # `strict`: a result per call is an invariant of the loop above, and a
            # silent mismatch would pair a result with the wrong call id.
            *(
                _tool_message(call, tool_result)
                for call, tool_result in zip(calls, results, strict=True)
            ),
        )

    if result is None:  # pragma: no cover - the loop always runs at least once
        result = await agent.execute(request, context)

    if result.message.tool_calls:
        # The iteration ceiling was reached while the model still wanted tools.
        # Its last message is a tool request, not an answer, so returning it
        # would show the user a blank reply.
        _logger.warning(
            "runtime.tool_loop_exhausted",
            agent_id=agent.descriptor.agent_id,
            model_calls=model_calls,
            limit=max_iterations,
            **context.to_log_fields(),
        )
        result = result.model_copy(
            update={
                "message": Message(
                    role=MessageRole.ASSISTANT,
                    content=(
                        "I was unable to finish this request within the allowed number of "
                        "tool calls. Please try narrowing the question."
                    ),
                ),
                "finish_reason": "tool_limit",
            }
        )

    return result.model_copy(
        update={"model_calls": model_calls, "tool_invocations": tool_invocations}
    )


async def stream_tool_loop(
    agent: Agent,
    request: AgentRequest,
    context: ExecutionContext,
    executor: ToolExecutor | None,
) -> AsyncGenerator[CompletionChunk, None]:
    """Stream ``agent``'s answer, running any tools it asks for on the way.

    The streaming counterpart of :func:`run_tool_loop`, and the reason the chat
    UI can search. Until this existed the streaming path handed the agent's
    chunks straight through, so the endpoint the browser uses — the only one it
    uses — could never invoke a tool. The non-streaming endpoint could. Users
    saw a platform that had search and did not use it.

    How a tool turn looks on the wire
        The model's first stream carries tool calls and no prose, so nothing is
        forwarded. The tools run, their results join the exchange, and the
        second stream carries the answer, which is forwarded token by token.
        The consumer sees one uninterrupted answer and never learns there were
        two model calls.

    Why the terminal chunk is held back
        Whether tools were requested is only known once the stream ends. A
        terminal chunk forwarded eagerly would tell the consumer the turn was
        complete while a tool call was still pending, ending the answer at an
        empty string. So it is buffered, and released only when the model
        finishes without asking for anything more.

    Usage accumulates across iterations. A per-iteration count would under-report
    a tool turn's real cost by however many calls it took.
    """
    permitted = agent.descriptor.tool_ids

    if executor is None or not permitted:
        # No tools in play: one stream, forwarded as-is.
        #
        # The inner iterator is closed explicitly. Delegating with `async for`
        # alone does *not* propagate `aclose()` to it — closing this generator
        # raises GeneratorExit at the `yield` and leaves the agent's generator
        # suspended, holding an open provider connection until the garbage
        # collector happens to reach it. "Stop generating" is exactly that path.
        stream = agent.stream(request, context)
        try:
            async for chunk in stream:
                yield chunk
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        return

    budget = agent.descriptor.budget
    max_iterations = budget.max_model_calls or DEFAULT_MAX_ITERATIONS
    max_tool_calls = budget.max_tool_invocations
    declarations = _declarations(executor, permitted)

    exchange: tuple[Message, ...] = ()
    model_calls = 0
    tool_invocations = 0
    total_usage = TokenUsage()

    while model_calls < max_iterations:
        calls: list[ToolCall] = []
        terminal: CompletionChunk | None = None
        text: list[str] = []

        stream = agent.stream(
            request.model_copy(update={"tool_exchange": exchange, "tools": declarations}),
            context,
        )
        try:
            async for chunk in stream:
                if chunk.tool_calls:
                    calls.extend(chunk.tool_calls)

                if chunk.finish_reason is not None or chunk.usage is not None:
                    terminal = chunk
                    continue

                if chunk.delta:
                    text.append(chunk.delta)
                    yield chunk
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

        model_calls += 1

        if terminal is not None and terminal.usage is not None:
            total_usage = TokenUsage(
                prompt_tokens=total_usage.prompt_tokens + terminal.usage.prompt_tokens,
                completion_tokens=total_usage.completion_tokens + terminal.usage.completion_tokens,
            )

        if not calls:
            yield CompletionChunk(
                delta="",
                finish_reason=(terminal.finish_reason if terminal else None) or "stop",
                usage=total_usage,
            )
            return

        if max_tool_calls is not None and tool_invocations + len(calls) > max_tool_calls:
            exchange = (
                *exchange,
                _assistant_request(text, calls),
                *(
                    _tool_message(
                        call,
                        ToolResult(
                            tool_id=call.tool_id,
                            call_id=call.call_id,
                            succeeded=False,
                            error_message=(
                                "This turn's tool budget is exhausted. "
                                "Answer with the information you already have."
                            ),
                        ),
                    )
                    for call in calls
                ),
            )
            continue

        results = [await _invoke(executor, call, context, permitted) for call in calls]
        tool_invocations += len(results)

        exchange = (
            *exchange,
            _assistant_request(text, calls),
            *(
                _tool_message(call, tool_result)
                for call, tool_result in zip(calls, results, strict=True)
            ),
        )

    # The ceiling was reached with the model still asking for tools. Saying so
    # beats the alternative, which is an answer that simply stops.
    _logger.warning(
        "runtime.stream_tool_loop_exhausted",
        agent_id=agent.descriptor.agent_id,
        model_calls=model_calls,
        limit=max_iterations,
        **context.to_log_fields(),
    )
    yield CompletionChunk(
        delta=(
            "I was unable to finish this request within the allowed number of "
            "tool calls. Please try narrowing the question."
        ),
    )
    yield CompletionChunk(delta="", finish_reason="tool_limit", usage=total_usage)


def _declarations(executor: ToolExecutor, permitted: tuple[str, ...]) -> tuple[ToolDescriptor, ...]:
    """Resolve the declarations for the tools this agent may call.

    The workflow layer owns this lookup because it owns the registry. A provider
    that resolved descriptors itself would couple inference to tooling, which is
    why the provider is handed finished declarations and never a registry.

    Only registered, available tools are returned — `available_tools` already
    skips the rest — so a model is never told about a tool this deployment
    cannot actually run.
    """
    return tuple(tool.descriptor for tool in executor.available_tools(permitted))


def _assistant_request(text: list[str], calls: list[ToolCall]) -> Message:
    """Rebuild the assistant turn that asked for these tools.

    The transcript has to contain the request the results answer. Any prose
    streamed alongside the calls is kept: a model that explained itself before
    calling a tool and then finds that explanation missing tends to repeat it.
    """
    return Message(
        role=MessageRole.ASSISTANT,
        content="".join(text),
        tool_calls=tuple(calls),
    )


async def _invoke(
    executor: ToolExecutor,
    call: ToolCall,
    context: ExecutionContext,
    permitted: tuple[str, ...],
) -> ToolResult:
    """Turn one model-emitted tool call into a result.

    Arguments arrive as a raw JSON string because models emit malformed JSON
    often enough that parsing has to be a validation step rather than an
    implicit part of deserialisation. A parse failure is reported back to the
    model, which can then correct itself.
    """
    try:
        arguments = json.loads(call.arguments) if call.arguments.strip() else {}
    except json.JSONDecodeError:
        return ToolResult(
            tool_id=call.tool_id,
            call_id=call.call_id,
            succeeded=False,
            error_message="Tool arguments were not valid JSON. Re-issue the call with valid JSON.",
        )

    if not isinstance(arguments, dict):
        return ToolResult(
            tool_id=call.tool_id,
            call_id=call.call_id,
            succeeded=False,
            error_message="Tool arguments must be a JSON object.",
        )

    return await executor.execute(
        ToolInvocation(tool_id=call.tool_id, arguments=arguments, call_id=call.call_id),
        context,
        permitted_tool_ids=permitted,
    )


def _tool_message(call: ToolCall, result: ToolResult) -> Message:
    """Render a tool result as a message the model can read.

    JSON rather than prose: the output schema is declared, and a model given
    structured data cites it more reliably than one given a paragraph. A failure
    is rendered as an object too, so success and failure parse the same way.
    """
    payload = (
        result.output
        if result.succeeded and result.output is not None
        else {"error": result.error_message or "The tool failed."}
    )

    return Message(
        role=MessageRole.TOOL,
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id=call.call_id,
    )
