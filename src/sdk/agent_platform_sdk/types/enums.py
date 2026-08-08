"""Platform enumerations.

The handbook requires enums instead of magic strings. Every member inherits
:class:`str` so values serialise directly to JSON and can be used as log and
span attribute values without conversion.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "Capability",
    "ErrorCategory",
    "ExecutionState",
    "HealthStatus",
    "MessageRole",
    "ResponseFormat",
]


class Capability(StrEnum):
    """A feature a provider or model may or may not support.

    Routing decisions must be made on capability, never on provider identity
    (``architecture.md`` §44). Asking "does this support tool calling?" keeps
    the runtime working when a new provider is added; asking "is this Azure?"
    does not.
    """

    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    FUNCTION_CALLING = "function_calling"
    STRUCTURED_OUTPUT = "structured_output"
    JSON_MODE = "json_mode"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    COST_REPORTING = "cost_reporting"


class HealthStatus(StrEnum):
    """Health of a single platform component.

    ``DEGRADED`` is distinct from ``UNHEALTHY``: a degraded component still
    serves traffic, so the runtime may keep using it while alerting, whereas an
    unhealthy component should be routed around.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class MessageRole(StrEnum):
    """Author of a message in a conversation.

    Deliberately provider-neutral. Providers translate to and from their own
    vocabulary inside the provider package.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ResponseFormat(StrEnum):
    """Shape the caller asks the model to produce.

    Values follow the OpenAI-style Chat API vocabulary, which every
    OpenAI-compatible endpoint already understands, so a future provider adapter
    passes the value straight through instead of translating it.

    Declared as part of the common request contract (``architecture.md`` §30).
    Honouring it is a provider concern: a provider must only accept a format for
    which the resolved model declares the matching capability
    (:attr:`Capability.JSON_MODE`, :attr:`Capability.STRUCTURED_OUTPUT`).
    """

    TEXT = "text"
    JSON_OBJECT = "json_object"


class ExecutionState(StrEnum):
    """Lifecycle state of a running agent (``architecture.md`` §14)."""

    REGISTERED = "registered"
    READY = "ready"
    EXECUTING = "executing"
    WAITING_FOR_TOOL = "waiting_for_tool"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorCategory(StrEnum):
    """Normalised failure classification (``architecture.md`` §22).

    The runtime maps every exception onto one of these before returning it, so
    that callers, retry logic and dashboards reason about a stable, small set of
    failure modes instead of provider-specific error codes.
    """

    CONFIGURATION = "configuration"
    VALIDATION = "validation"
    PROVIDER = "provider"
    NETWORK = "network"
    TOOL = "tool"
    MEMORY = "memory"
    TIMEOUT = "timeout"
    POLICY_VIOLATION = "policy_violation"
    NOT_FOUND = "not_found"
    UNEXPECTED = "unexpected"
