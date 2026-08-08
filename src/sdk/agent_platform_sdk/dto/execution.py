"""Agent execution contracts.

What the runtime hands an agent, and what an agent hands back. Both are
provider-neutral and both are immutable.

The division of labour these types encode is the whole point of the runtime
(``architecture.md`` §9): by the time an :class:`AgentRequest` exists, memory has
been retrieved, the prompt has been resolved and the model has been selected. The
agent receives a complete picture and is responsible only for reasoning within
it. An agent that had to load its own history would be doing the runtime's job,
and every agent would do it slightly differently.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.dto.completion import TokenUsage
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.prompt import PromptAsset
from agent_platform_sdk.dto.tool import ToolDescriptor

__all__ = ["AgentRequest", "AgentResult"]


class AgentRequest(BaseModel):
    """Everything an agent needs to produce one response.

    Assembled by the runtime. Deterministic and side-effect free to build, which
    is what makes context assembly testable (``architecture.md``, "Context
    Assembly").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: str = Field(description="The user's message for this turn.")
    history: tuple[Message, ...] = Field(
        default=(),
        description=(
            "Conversation so far, oldest first, already retrieved from memory by "
            "the runtime. Excludes `input`, which the agent appends itself."
        ),
    )
    prompt: PromptAsset | None = Field(
        default=None,
        description=(
            "Resolved prompt asset. Resolved by the runtime through the prompt "
            "registry, so an agent never reads a file and a pinned version is "
            "honoured without the agent knowing versions exist."
        ),
    )
    variables: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Values for the prompt's declared variables. Strings only: these are "
            "rendered into text sent to a model, and a structured value would have "
            "to be serialised by some convention the prompt author cannot see."
        ),
    )
    tool_exchange: tuple[Message, ...] = Field(
        default=(),
        description=(
            "Messages produced *after* `input` during a tool-calling turn: the "
            "assistant's tool request, then each tool's result. Separate from "
            "`history` because ordering matters — they belong after the user's "
            "message, and history belongs before it. Empty on a first call."
        ),
    )
    tools: tuple[ToolDescriptor, ...] = Field(
        default=(),
        description=(
            "Tools this turn may call, with their schemas. Supplied by the "
            "workflow layer from the tool registry; the agent passes them "
            "through to the model request without interpreting them."
        ),
    )
    model_id: str = Field(description="Model the runtime selected for this turn.")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, gt=0)


class AgentResult(BaseModel):
    """The outcome of one agent execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: Message = Field(description="The agent's response.")
    agent_id: str = Field(description="Agent that produced it.")
    model_id: str = Field(description="Model that served the call.")
    provider_id: str = Field(description="Provider that served it.")
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    finish_reason: str | None = Field(default=None)
    model_calls: int = Field(
        default=1,
        ge=0,
        description=(
            "Model calls this execution made. One today; a reasoning loop or a "
            "tool-calling turn makes several, and budget enforcement counts them."
        ),
    )
    tool_invocations: int = Field(default=0, ge=0, description="Tool calls made. Milestone 04.")
