"""Public contract surface of the Enterprise Multi-Agent AI Platform.

Interfaces, data contracts, events and policies — never implementations. See
``src/sdk/README.md`` for the rules this package holds itself to.

Re-exported here so consumers can write ``from agent_platform_sdk import LLMProvider``
without needing to know the internal module layout, which lets modules move
without breaking callers.
"""

from agent_platform_sdk.contracts import ComponentHealth, ExecutionContext, HealthReport
from agent_platform_sdk.dto import (
    AgentDescriptor,
    AgentRequest,
    AgentResult,
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    Message,
    ModelDescriptor,
    ModelPricing,
    TokenUsage,
    ToolCall,
    ToolDescriptor,
    ToolInvocation,
    ToolResult,
)
from agent_platform_sdk.dto.evaluation import EvaluationRecord
from agent_platform_sdk.dto.prompt import PromptAsset, PromptVariable
from agent_platform_sdk.dto.search import SearchQuery, SearchResult, SearchResults
from agent_platform_sdk.events import RuntimeEvent, RuntimeEventName
from agent_platform_sdk.interfaces import (
    Agent,
    EmbeddingProvider,
    EvaluationProvider,
    EventPublisher,
    LLMGateway,
    LLMProvider,
    LLMProviderResolver,
    MemoryProvider,
    PromptProvider,
    Provider,
    Registry,
    SearchProvider,
    ToolProvider,
    VectorRecord,
    VectorStoreProvider,
    WorkflowEngine,
)
from agent_platform_sdk.policies import BudgetPolicy, RetryPolicy, TimeoutPolicy
from agent_platform_sdk.types import (
    Capability,
    ErrorCategory,
    ExecutionState,
    HealthStatus,
    MessageRole,
    ResponseFormat,
)

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "AgentDescriptor",
    "AgentRequest",
    "AgentResult",
    "BudgetPolicy",
    "Capability",
    "CompletionChunk",
    "CompletionRequest",
    "CompletionResponse",
    "ComponentHealth",
    "EmbeddingProvider",
    "ErrorCategory",
    "EvaluationProvider",
    "EvaluationRecord",
    "EventPublisher",
    "ExecutionContext",
    "ExecutionState",
    "HealthReport",
    "HealthStatus",
    "LLMGateway",
    "LLMProvider",
    "LLMProviderResolver",
    "MemoryProvider",
    "Message",
    "MessageRole",
    "ModelDescriptor",
    "ModelPricing",
    "PromptAsset",
    "PromptProvider",
    "PromptVariable",
    "Provider",
    "Registry",
    "ResponseFormat",
    "RetryPolicy",
    "RuntimeEvent",
    "RuntimeEventName",
    "SearchProvider",
    "SearchQuery",
    "SearchResult",
    "SearchResults",
    "TimeoutPolicy",
    "TokenUsage",
    "ToolCall",
    "ToolDescriptor",
    "ToolInvocation",
    "ToolProvider",
    "ToolResult",
    "VectorRecord",
    "VectorStoreProvider",
    "WorkflowEngine",
    "__version__",
]
