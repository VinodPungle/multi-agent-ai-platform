"""Model Context Protocol support.

Responsibility
    Making tools hosted on MCP servers available to agents as ordinary
    :class:`~agent_platform_sdk.interfaces.tool_provider.ToolProvider` instances.

Design rule
    ``CLAUDE.md`` is specific about this one: *"Do not tightly couple tools to
    MCP. Design the Tool Registry so tools can be backed by local
    implementations, REST APIs, Azure Functions or MCP servers. Future additions
    should require only a new adapter."*

    So this package is an adapter and nothing more. The runtime, the tool
    executor, the workflow engine and every agent are unchanged and unaware —
    an MCP tool is resolved, validated, timed, retried, logged and budgeted by
    exactly the same code path as the internet-search tool.

    The MCP SDK is imported in one module (:mod:`streamable_http_session`) and
    nowhere else. Everything above it speaks platform-owned types.

Added in Milestone 09.
"""
