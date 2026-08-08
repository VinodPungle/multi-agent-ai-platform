"""Tool registry and invocation contracts.

Agents never call tools directly (``architecture.md`` §32-33). They declare
intent; the runtime resolves the descriptor, enforces permissions and policy,
executes, and returns a :class:`ToolResult`. Centralising this is what makes
logging, retries, authorisation and auditing possible in one place.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.policies.retry import RetryPolicy

__all__ = ["ToolDescriptor", "ToolInvocation", "ToolResult"]


class ToolDescriptor(BaseModel):
    """Registry metadata describing one executable tool.

    Schemas are JSON Schema documents rather than Python types because the same
    declaration is sent to models for tool calling, published in the API, and
    used to validate arguments. A single representation keeps them in step.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_id: str = Field(description="Stable identifier used by agents and the registry.")
    description: str = Field(
        description="Explains to a model when to use the tool. This text is prompt material."
    )
    version: str = Field(default="1.0", description="Descriptor version.")
    owner: str | None = Field(default=None, description="Team accountable for the tool.")

    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for arguments. Validated before execution.",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for the payload returned on success.",
    )

    required_permissions: tuple[str, ...] = Field(
        default=(),
        description="Permissions the caller must hold. Enforced by the runtime, not the tool.",
    )
    timeout_seconds: float = Field(default=30.0, gt=0)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    is_available: bool = Field(
        default=True,
        description="Set false to withdraw a tool from routing without removing its config.",
    )


class ToolInvocation(BaseModel):
    """A validated request to execute a tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_id: str = Field(description="Tool to execute.")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments already validated against the tool's input schema.",
    )
    call_id: str | None = Field(
        default=None,
        description="Model-assigned call id, echoed back so the result can be matched.",
    )


class ToolResult(BaseModel):
    """The structured outcome of a tool execution.

    Failures are represented as a value with ``succeeded=False`` rather than as
    an exception, because a failing tool is usually something the agent should
    reason about and recover from, not something that should abort the request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_id: str = Field(description="Tool that produced this result.")
    call_id: str | None = Field(default=None, description="Echoed invocation call id.")
    succeeded: bool = Field(description="Whether the tool completed successfully.")
    output: dict[str, Any] | None = Field(
        default=None,
        description="Payload matching the tool's output schema. None on failure.",
    )
    error_message: str | None = Field(
        default=None,
        description="Operator- and model-safe failure summary. Never a stack trace.",
    )
    latency_ms: float | None = Field(default=None, ge=0)
