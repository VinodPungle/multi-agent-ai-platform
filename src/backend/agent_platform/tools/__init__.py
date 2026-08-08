"""Tool implementations and the execution pipeline.

Responsibility
    Concrete ``ToolProvider`` implementations, and the executor that runs them
    under platform policy.

Design rule
    Agents never call tools (``architecture.md`` §33). They declare which tools
    they may use; the runtime resolves, authorises, validates, executes and
    returns a ``ToolResult``. Centralising that is what makes logging, retries,
    authorisation and auditing exist once rather than once per integration.

Backing technologies
    The same ``ToolProvider`` interface backs local implementations, REST APIs,
    Azure Functions and — through a future adapter — MCP servers. Adding one is
    an adapter, never a change to the runtime.
"""

from agent_platform.tools.internet_search_tool import (
    INTERNET_SEARCH_TOOL_ID,
    InternetSearchTool,
)
from agent_platform.tools.tool_executor import ToolExecutor

__all__ = ["INTERNET_SEARCH_TOOL_ID", "InternetSearchTool", "ToolExecutor"]
