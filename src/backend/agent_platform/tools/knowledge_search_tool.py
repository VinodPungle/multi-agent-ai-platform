"""The knowledge base search tool.

Retrieval as a tool, not as a prompt preamble. That is the design decision worth
defending, because the alternative — retrieve on every turn and prepend the
passages — is what most tutorials do.

Making it a tool means:

* the model decides when documents are needed, so a turn that needs none spends
  no context on them and costs one model call;
* the runtime applies authorisation, timeout, retry, telemetry and budget to
  retrieval exactly as it does to every other tool;
* an agent that should not see internal documents simply does not list it;
* the user can see *what was searched for*, because the query is the model's and
  it is reported.

The cost is that the model has to choose to search, which is prompt engineering
and is the same trade already accepted for internet search.

**No results is a success.** A question the corpus cannot answer returns
``succeeded=True`` with an empty list, because "I searched our documents and
found nothing" is a useful answer. Reporting it as a failure would push the
model to retry a query that will find nothing again — and, worse, invite it to
answer from memory without saying the corpus was silent.
"""

from __future__ import annotations

from typing import Any

from agent_platform.exceptions.base import PlatformError, ValidationError
from agent_platform.knowledge.retriever import KnowledgeRetriever
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.knowledge import RetrievedPassage
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["KNOWLEDGE_SEARCH_TOOL_ID", "KnowledgeSearchTool"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

KNOWLEDGE_SEARCH_TOOL_ID = "knowledge-search"

#: The most passages a caller may ask for. A model told to gather "everything
#: relevant" will ask for a large number, and every passage returned is prompt
#: context spent — and paid for — on the next model call.
_MAX_PASSAGES = 10

#: Longest query accepted. A model occasionally pastes an entire conversation
#: into a search box; embedding that matches nothing in particular and costs
#: more than the search is worth.
_MAX_QUERY_CHARACTERS = 400


class KnowledgeSearchTool:
    """Searches the platform's knowledge base.

    Satisfies :class:`~agent_platform_sdk.interfaces.tool_provider.ToolProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        timeout_seconds: float = 15.0,
        max_passages: int = 5,
    ) -> None:
        """Create the tool.

        Args:
            retriever: Where passages come from. The interface, never a vector
                database.
            timeout_seconds: Declared on the descriptor and enforced by the
                runtime, not here.
            max_passages: Default passage count when the caller does not ask.
        """
        self._retriever = retriever
        self._timeout_seconds = timeout_seconds
        self._max_passages = min(max_passages, _MAX_PASSAGES)

    # -- Provider ----------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """Identifier this tool is registered under."""
        return KNOWLEDGE_SEARCH_TOOL_ID

    @property
    def descriptor(self) -> ToolDescriptor:
        """Registry metadata, including the schema sent to models.

        The description is prompt material — it is what a model reads to decide
        whether to call this rather than searching the internet or answering
        from memory — so it states the distinction explicitly. A description
        that merely said "search documents" produces a model that uses this for
        general knowledge and the internet for company policy.
        """
        return ToolDescriptor(
            tool_id=KNOWLEDGE_SEARCH_TOOL_ID,
            description=(
                "Search the organisation's own documents and knowledge base. Use this "
                "for internal policies, product documentation, runbooks and anything "
                "specific to this organisation — information that would not appear on "
                "the public internet. Prefer it over internet search whenever the "
                "question is about how *this* organisation does something. Always cite "
                "the sources it returns."
            ),
            version="1.0",
            owner="platform-team",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What to look for, as a natural-language question or "
                            "description of the topic."
                        ),
                        "minLength": 1,
                        "maxLength": _MAX_QUERY_CHARACTERS,
                    },
                    "max_passages": {
                        "type": "integer",
                        "description": f"How many passages to return (1-{_MAX_PASSAGES}).",
                        "minimum": 1,
                        "maximum": _MAX_PASSAGES,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "passage_count": {"type": "integer"},
                    "passages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "source": {"type": "string"},
                                "content": {"type": "string"},
                                "score": {"type": "number"},
                            },
                        },
                    },
                },
            },
            timeout_seconds=self._timeout_seconds,
            # Retrieval is a read with no side effects, so retrying is safe. Two
            # attempts covers a transient embedding-service blip without turning
            # an outage into a long wait.
            retry_policy=RetryPolicy(max_attempts=2),
        )

    async def initialize(self) -> None:
        """Initialisation belongs to the embedding and vector providers."""

    async def health_check(self) -> ComponentHealth:
        """Report that the tool is wired.

        The components that can actually be unhealthy — the embedding provider
        and the vector store — report their own health, and reporting theirs
        again here would double-count a single failure in the readiness summary.
        """
        return ComponentHealth(
            name=KNOWLEDGE_SEARCH_TOOL_ID,
            status=HealthStatus.HEALTHY,
            detail="Knowledge base retrieval.",
        )

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. A tool's capability is described by its schema."""
        del capability
        return False

    async def close(self) -> None:
        """The providers own their own lifecycles."""

    # -- Tool --------------------------------------------------------------

    async def validate(self, invocation: ToolInvocation) -> None:
        """Check the arguments before any budget is spent.

        Hand-written, matching `internet-search`: two properties, and pulling in
        a schema validator to check them would be more machinery than the thing
        it checks. The MCP tools validate with `jsonschema` because their schemas
        come from servers nobody here controls; this one is written here.

        Raises:
            ValidationError: the arguments cannot be executed as given.
        """
        query = invocation.arguments.get("query")

        if not isinstance(query, str) or not query.strip():
            message = f"{KNOWLEDGE_SEARCH_TOOL_ID} requires a non-empty 'query' argument."
            raise ValidationError(message, details={"tool_id": KNOWLEDGE_SEARCH_TOOL_ID})

        if len(query) > _MAX_QUERY_CHARACTERS:
            message = (
                f"A knowledge query cannot exceed {_MAX_QUERY_CHARACTERS} characters. "
                f"This one is {len(query)}."
            )
            raise ValidationError(message, details={"tool_id": KNOWLEDGE_SEARCH_TOOL_ID})

        max_passages = invocation.arguments.get("max_passages")
        if max_passages is not None and (
            not isinstance(max_passages, int)
            or isinstance(max_passages, bool)
            or not 1 <= max_passages <= _MAX_PASSAGES
        ):
            message = f"'max_passages' must be an integer between 1 and {_MAX_PASSAGES}."
            raise ValidationError(message, details={"tool_id": KNOWLEDGE_SEARCH_TOOL_ID})

    async def execute(
        self,
        invocation: ToolInvocation,
        context: ExecutionContext,
    ) -> ToolResult:
        """Retrieve passages and return them."""
        query = str(invocation.arguments["query"]).strip()
        requested = invocation.arguments.get("max_passages")
        limit = requested if isinstance(requested, int) else self._max_passages

        with _tracer.start_as_current_span("tool.knowledge_search") as span:
            span.set_attribute("tool.id", KNOWLEDGE_SEARCH_TOOL_ID)
            # The query is user content and stays out of span attributes.
            span.set_attribute("knowledge.query_length", len(query))

            try:
                passages = await self._retriever.retrieve(
                    query,
                    context,
                    limit=min(limit, _MAX_PASSAGES),
                )
            except PlatformError as error:
                # Returned rather than raised. An agent that knows its knowledge
                # base is unavailable can say so; an exception aborts the turn.
                _logger.warning(
                    "tool.knowledge_search_failed",
                    tool_id=KNOWLEDGE_SEARCH_TOOL_ID,
                    error_type=type(error).__name__,
                    **context.to_log_fields(),
                )
                return ToolResult(
                    tool_id=KNOWLEDGE_SEARCH_TOOL_ID,
                    call_id=invocation.call_id,
                    succeeded=False,
                    error_message=error.message,
                )

            span.set_attribute("knowledge.passage_count", len(passages))

            return ToolResult(
                tool_id=KNOWLEDGE_SEARCH_TOOL_ID,
                call_id=invocation.call_id,
                succeeded=True,
                output=_to_output(query, passages),
            )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"KnowledgeSearchTool(max_passages={self._max_passages})"


def _to_output(query: str, passages: tuple[RetrievedPassage, ...]) -> dict[str, Any]:
    """Shape passages into the tool's declared output schema.

    Title, source, content and score reach the model. `document_id` and
    `chunk_index` do not: they are storage details the model cannot use, and
    every field returned is context spent on the next call.

    The score is included because it lets a model weigh a weak match rather than
    treating every returned passage as equally authoritative.
    """
    return {
        "query": query,
        "passage_count": len(passages),
        "passages": [
            {
                "title": passage.title,
                "source": passage.source,
                "content": passage.content,
                "score": round(passage.score, 4),
            }
            for passage in passages
        ],
    }
