"""Model invocation contracts.

These are the types every :class:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider`
accepts and returns. Because they are provider-neutral, swapping Azure AI Foundry
for Anthropic changes no caller.

Together they are the *common request model* and *common response model* of
``architecture.md`` §30. Field names deliberately track the OpenAI-style Chat API
vocabulary — ``temperature``, ``top_p``, ``stop``, ``response_format`` — because
that is the dialect every OpenAI-compatible endpoint already speaks. An adapter
for such an endpoint then becomes a rename, not a translation layer.

No field here may hold a vendor object. Provider-side detail travels as strings
in :attr:`CompletionResponse.provider_metadata`, which is what keeps an SDK type
from becoming a place a vendor payload can hide.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.dto.message import Message, ToolCall
from agent_platform_sdk.dto.tool import ToolDescriptor
from agent_platform_sdk.types.enums import ResponseFormat

__all__ = [
    "CompletionChunk",
    "CompletionRequest",
    "CompletionResponse",
    "TokenUsage",
]


class TokenUsage(BaseModel):
    """Token accounting for a single model call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0, description="Tokens in the assembled prompt.")
    completion_tokens: int = Field(default=0, ge=0, description="Tokens generated.")

    @property
    def total_tokens(self) -> int:
        """Total tokens billed for the call."""
        return self.prompt_tokens + self.completion_tokens


class CompletionRequest(BaseModel):
    """A provider-neutral request for a model completion.

    ``model_id`` is resolved by the runtime from the model registry before this
    object is built. Providers receive an already-resolved identifier and never
    choose a model themselves.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = Field(description="Registry identifier of the model to invoke.")
    messages: tuple[Message, ...] = Field(description="Conversation, oldest message first.")
    system_prompt: str | None = Field(
        default=None,
        description=(
            "Instruction governing the whole exchange, carried separately from "
            "`messages` because providers disagree about where it belongs: some take a "
            "dedicated parameter, others expect a leading system message. Keeping it "
            "distinct lets each adapter place it correctly instead of forcing one "
            "convention on all of them."
        ),
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. None defers to the model's registered default.",
    )
    top_p: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "Nucleus sampling threshold. None defers to the provider default. Setting "
            "this together with `temperature` is accepted but rarely intended — most "
            "providers document that one or the other should be tuned, not both."
        ),
    )
    max_output_tokens: int | None = Field(
        default=None,
        gt=0,
        description="Cap on generated tokens. None defers to the model's registered default.",
    )
    stop_sequences: tuple[str, ...] = Field(
        default=(),
        description="Sequences that terminate generation.",
    )
    tool_ids: tuple[str, ...] = Field(
        default=(),
        description="Tools the model may call, resolved through the tool registry.",
    )
    tools: tuple[ToolDescriptor, ...] = Field(
        default=(),
        description=(
            "Full declarations for the tools the model may call. Ids alone are "
            "not enough: a provider can only tell the model a tool exists, not "
            "what arguments it takes, so the model either cannot call it or "
            "calls it with nothing. Populated by the workflow layer, which owns "
            "the tool registry — the provider must never read that registry "
            "itself, or inference becomes coupled to tooling."
        ),
    )
    response_format: ResponseFormat | None = Field(
        default=None,
        description=(
            "Requested output shape. None leaves the provider default in place. A "
            "provider must reject a format the resolved model does not declare a "
            "capability for, rather than silently returning prose."
        ),
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Caller-supplied labels echoed into telemetry — experiment arm, prompt "
            "variant, evaluation run. Strings only, and never user content or "
            "credentials: these values reach logs and traces."
        ),
    )


class CompletionResponse(BaseModel):
    """The result of a non-streaming model completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: Message = Field(description="The assistant message produced by the model.")
    model_id: str = Field(description="Model that actually served the request.")
    provider_id: str = Field(description="Provider that served the request.")
    usage: TokenUsage = Field(
        default_factory=TokenUsage,
        description="Token accounting. Zeroed when a provider does not report usage.",
    )
    estimated_cost: Decimal | None = Field(
        default=None,
        ge=0,
        description=(
            "Cost in USD, computed from registry pricing. Decimal rather than float "
            "because summing float costs across millions of calls accumulates error."
        ),
    )
    latency_ms: float | None = Field(default=None, ge=0, description="Total call latency.")
    finish_reason: str | None = Field(
        default=None,
        description="Why generation stopped, normalised by the provider adapter.",
    )
    provider_metadata: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Provider-side facts worth keeping for diagnosis — the vendor's own request "
            "id, the region that served the call, a rate-limit remainder. Flattened to "
            "strings at the provider boundary so that no vendor object escapes it."
        ),
    )
    model_metadata: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "What the model actually was, as opposed to what was asked for: resolved "
            "version, deployment name, revision. The distinction matters when a "
            "provider silently upgrades a deployment underneath a stable model id."
        ),
    )


class CompletionChunk(BaseModel):
    """One increment of a streamed completion.

    Streaming is coordinated by the runtime (``architecture.md`` §24), which
    measures time-to-first-token from the first chunk it observes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    delta: str = Field(default="", description="Text appended by this chunk.")
    tool_calls: tuple[ToolCall, ...] = Field(
        default=(),
        description="Tool calls completed within this chunk.",
    )
    finish_reason: str | None = Field(
        default=None,
        description="Set on the final chunk only.",
    )
    usage: TokenUsage | None = Field(
        default=None,
        description="Usage, when the provider reports it on the terminal chunk.",
    )
