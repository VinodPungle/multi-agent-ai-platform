"""The internet search tool.

The platform's first tool, and the reference for every tool that follows —
GitHub, Jira, SQL, SharePoint, and eventually MCP servers behind an adapter.

It is a thin translation layer over a
:class:`~agent_platform_sdk.interfaces.search_provider.SearchProvider`: validate
arguments, call the provider, shape results into a ``ToolResult``. It names no
search backend, so switching from DuckDuckGo to a keyed provider changes
configuration and nothing here.

Two behaviours worth stating outright, because both are choices:

**No results is a success.** A query that matches nothing returns
``succeeded=True`` with an empty list. It is an answer the agent should reason
about — "I searched and found nothing" is useful, and reporting it as a failure
would push the agent toward retrying a query that will match nothing again.

**A provider outage is a failure the agent can see.** It returns
``succeeded=False`` with a safe message rather than raising, because an agent
that knows its tool is unavailable can say so, whereas an exception aborts the
whole turn.
"""

from __future__ import annotations

from typing import Any

from agent_platform.exceptions.base import PlatformError, ValidationError
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.search import SearchQuery
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.interfaces.search_provider import SearchProvider
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.types.enums import Capability

__all__ = ["INTERNET_SEARCH_TOOL_ID", "InternetSearchTool"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

INTERNET_SEARCH_TOOL_ID = "internet-search"

#: The maximum a caller may ask for. A model asked for "as many as possible"
#: will happily request hundreds; every one of them lands in the next prompt.
_MAX_RESULTS = 10


class InternetSearchTool:
    """Searches the internet through the configured search provider.

    Satisfies :class:`~agent_platform_sdk.interfaces.tool_provider.ToolProvider`
    structurally.
    """

    def __init__(
        self,
        provider: SearchProvider,
        timeout_seconds: float = 15.0,
        max_results: int = 5,
    ) -> None:
        """Create the tool.

        Args:
            provider: Where results come from. The interface, never a backend.
            timeout_seconds: Declared on the descriptor and enforced by the
                runtime, not here — a tool that policed its own timeout would be
                one of several implementations of the same policy.
            max_results: Default result count when the caller does not ask.
        """
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._max_results = min(max_results, _MAX_RESULTS)

    # -- Provider ----------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """Identifier this tool is registered under."""
        return INTERNET_SEARCH_TOOL_ID

    @property
    def descriptor(self) -> ToolDescriptor:
        """Registry metadata, including the schema sent to models.

        The description is prompt material: it is what a model reads to decide
        whether to call this tool, so it states when to use it *and* when not
        to. A vague description produces a model that searches for everything.
        """
        return ToolDescriptor(
            tool_id=INTERNET_SEARCH_TOOL_ID,
            description=(
                "Search the internet for current information. Use this when the answer "
                "depends on recent events, live data, or facts you are not confident "
                "about. Do not use it for reasoning, arithmetic, or anything already "
                "present in the conversation."
            ),
            version="1.0",
            owner="platform-team",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for, as a natural-language query.",
                        "minLength": 1,
                        "maxLength": 400,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"How many results to return (1-{_MAX_RESULTS}).",
                        "minimum": 1,
                        "maximum": _MAX_RESULTS,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "provider_id": {"type": "string"},
                    "result_count": {"type": "integer"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "snippet": {"type": "string"},
                            },
                        },
                    },
                },
            },
            timeout_seconds=self._timeout_seconds,
            retry_policy=RetryPolicy(max_attempts=2),
        )

    async def initialize(self) -> None:
        """Initialisation belongs to the search provider, which owns the connection."""

    async def health_check(self) -> ComponentHealth:
        """Report the health of the provider behind the tool."""
        return await self._provider.health_check()

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Tool capability is described by its schema."""
        del capability
        return False

    async def close(self) -> None:
        """The search provider owns its own lifecycle."""

    # -- Tool --------------------------------------------------------------

    async def validate(self, invocation: ToolInvocation) -> None:
        """Check the arguments before any budget or side effect is spent.

        Hand-written rather than a JSON Schema validator: the schema has two
        properties, and adding a validation dependency to check them would be
        more machinery than the thing it checks. That trade reverses as soon as
        a tool has a genuinely complex schema, and this is where it changes.

        Raises:
            ValidationError: the arguments cannot be executed as given.
        """
        query = invocation.arguments.get("query")

        if not isinstance(query, str) or not query.strip():
            message = "internet-search requires a non-empty 'query' argument."
            raise ValidationError(message, details={"tool_id": INTERNET_SEARCH_TOOL_ID})

        if len(query) > 400:
            message = f"A search query cannot exceed 400 characters. This one is {len(query)}."
            raise ValidationError(message, details={"tool_id": INTERNET_SEARCH_TOOL_ID})

        max_results = invocation.arguments.get("max_results")
        if max_results is not None and (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= _MAX_RESULTS
        ):
            message = f"'max_results' must be an integer between 1 and {_MAX_RESULTS}."
            raise ValidationError(message, details={"tool_id": INTERNET_SEARCH_TOOL_ID})

    async def execute(
        self,
        invocation: ToolInvocation,
        context: ExecutionContext,
    ) -> ToolResult:
        """Run the search and return structured results."""
        query_text = str(invocation.arguments["query"]).strip()
        requested = invocation.arguments.get("max_results")
        max_results = requested if isinstance(requested, int) else self._max_results

        with _tracer.start_as_current_span("tool.internet_search") as span:
            span.set_attribute("tool.id", INTERNET_SEARCH_TOOL_ID)
            span.set_attribute("search.provider_id", self._provider.provider_id)
            # The query itself is deliberately not a span attribute: it is user
            # content, and spans are exported to systems with different
            # retention and access rules than the request.
            span.set_attribute("search.query_length", len(query_text))

            try:
                results = await self._provider.search(
                    SearchQuery(query=query_text, max_results=min(max_results, _MAX_RESULTS)),
                    context,
                )
            except PlatformError as error:
                # Returned rather than raised: an agent that knows its tool is
                # unavailable can say so; an exception aborts the whole turn.
                _logger.warning(
                    "tool.search_failed",
                    tool_id=INTERNET_SEARCH_TOOL_ID,
                    error_type=type(error).__name__,
                    **context.to_log_fields(),
                )
                return ToolResult(
                    tool_id=INTERNET_SEARCH_TOOL_ID,
                    call_id=invocation.call_id,
                    succeeded=False,
                    error_message=error.message,
                )

            span.set_attribute("search.result_count", len(results.results))

            return ToolResult(
                tool_id=INTERNET_SEARCH_TOOL_ID,
                call_id=invocation.call_id,
                succeeded=True,
                output=self._to_output(results.query, results.provider_id, results),
                latency_ms=results.latency_ms,
            )

    @staticmethod
    def _to_output(query: str, provider_id: str, results: Any) -> dict[str, Any]:  # noqa: ANN401
        """Shape results into the tool's declared output schema.

        Only title, url and snippet reach the model. Scores and timestamps are
        provider-specific and would be spent context for no benefit.
        """
        return {
            "query": query,
            "provider_id": provider_id,
            "result_count": len(results.results),
            "results": [
                {"title": result.title, "url": result.url, "snippet": result.snippet}
                for result in results.results
            ],
        }
