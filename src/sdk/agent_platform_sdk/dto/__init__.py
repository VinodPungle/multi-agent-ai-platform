"""Data transfer objects exchanged across layer and process boundaries.

Every type here is provider-neutral and immutable. Provider adapters translate
vendor payloads into these shapes, which is what keeps vendor types out of the
application and domain layers.
"""

from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message, ToolCall
from agent_platform_sdk.dto.model import ModelDescriptor, ModelPricing
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult

__all__ = [
    "AgentDescriptor",
    "CompletionChunk",
    "CompletionRequest",
    "CompletionResponse",
    "Message",
    "ModelDescriptor",
    "ModelPricing",
    "TokenUsage",
    "ToolCall",
    "ToolDescriptor",
    "ToolInvocation",
    "ToolResult",
]
