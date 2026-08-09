"""The MCP client. The only module in the platform that imports the MCP SDK.

Transport is Streamable HTTP, which is the transport an *enterprise* platform
can actually use: stdio means spawning a subprocess from a container, which is a
supply-chain and isolation problem rather than an integration.

Connect per call, deliberately
    Each :meth:`list_tools` and :meth:`call_tool` opens a session, does its
    work, and closes. The alternative — hold a session open and reuse it — is
    faster and was rejected for two reasons, in order of importance:

    1. **Lifetime correctness.** The SDK's transport is an async context manager
       built on anyio task groups. Entering it during application startup and
       exiting it during shutdown means the enter and the exit happen in
       different tasks, which is precisely the case anyio cancel scopes do not
       support. The failure mode is not a clean error; it is a hang or a
       spurious cancellation somewhere unrelated.
    2. **Recovery.** A pooled session that dies with the server stays dead. A
       per-call session reconnects on the next call with no reconnect logic at
       all.

    The cost is one handshake per tool call — tens of milliseconds against tool
    calls that already take hundreds. It is a real cost and it is the first
    thing to revisit if MCP tool latency ever matters; the seam for doing so is
    :class:`~agent_platform.tools.mcp.session.MCPSession`, so pooling would be a
    second implementation rather than a change here.

Authentication is deliberately absent
    MCP servers that need credentials are reached through a header supplied by
    configuration, and the platform holds no token of its own. OAuth flows to
    third-party MCP servers are a governance decision — who consents, on whose
    behalf, with what audit trail — and inventing one here would be inventing
    authorisation, which ``CLAUDE.md`` defers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters

from agent_platform.exceptions.base import ProviderError
from agent_platform.telemetry.logging import get_logger
from agent_platform.tools.mcp.session import MCPToolDefinition, MCPToolOutcome

__all__ = ["StreamableHTTPMCPSession"]

_logger = get_logger(__name__)


class StreamableHTTPMCPSession:
    """Talks to one MCP server over Streamable HTTP.

    Satisfies :class:`~agent_platform.tools.mcp.session.MCPSession`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        server_id: str,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Create the session factory.

        Args:
            server_id: Platform-side identifier. Namespaces this server's tool
                ids, so two servers exposing a tool called ``search`` do not
                collide.
            url: The server's Streamable HTTP endpoint.
            headers: Sent on every request. Where an API key goes, when a server
                requires one — held as a secret in configuration and never
                logged here.
            timeout_seconds: Per-request budget. A server that hangs would
                otherwise hold a chat turn open for as long as it likes.
        """
        self._server_id = server_id
        self._url = url
        self._headers = headers or {}
        self._timeout_seconds = timeout_seconds

    @property
    def server_id(self) -> str:
        """Identifier for this configured server."""
        return self._server_id

    async def list_tools(self) -> tuple[MCPToolDefinition, ...]:
        """Return every tool the server advertises."""
        listed = await self._guarded("list_tools", self._list_tools())

        return tuple(
            MCPToolDefinition(
                name=tool.name,
                # `title` is the human label and `description` the model-facing
                # text; falling back to the name is better than an empty
                # description, which gives a model nothing to decide on.
                description=tool.description or tool.title or tool.name,
                # `input_schema`, not `inputSchema`: the SDK renamed it at 2.0.
                # Found by introspecting the installed package rather than
                # trusting the older API from memory.
                input_schema=dict(tool.input_schema or {}),
                output_schema=dict(tool.output_schema or {}),
            )
            for tool in listed.tools
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolOutcome:
        """Invoke a tool and return its outcome."""
        result = await self._guarded(f"call_tool({name})", self._call_tool(name, arguments))

        return MCPToolOutcome(
            text=_text_of(result),
            structured_content=_structured_of(result),
            # The protocol's own tool-level failure flag. Carried through rather
            # than raised: the tool ran, and its complaint is something the
            # agent should read and act on.
            is_error=bool(getattr(result, "is_error", False)),
        )

    # -- Internals ---------------------------------------------------------

    async def _list_tools(self) -> Any:  # noqa: ANN401 - SDK type, not leaked
        async with self._session() as session:
            return await session.list_tools()

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:  # noqa: ANN401
        async with self._session() as session:
            return await session.call_tool(
                name,
                arguments,
                read_timeout_seconds=self._timeout_seconds,
            )

    async def _guarded(self, operation: str, work: Coroutine[Any, Any, Any]) -> Any:  # noqa: ANN401
        """Run one SDK operation in its own task and translate its failures.

        The isolation is the interesting part, and it is not defensive
        programming — it is the only way to tell two situations apart.

        When the server is unreachable, the SDK unwinds its anyio cancel scopes
        by cancelling the *running task*, and what finally escapes is a bare
        ``asyncio.CancelledError``. That is indistinguishable from a caller
        cancelling us: measured on both paths, ``cancelling()`` is 1 and
        ``uncancel()`` returns 0. The SDK destroys the distinction.

        Running the operation in a task of its own restores it. The SDK cancels
        *that* task; ``shield`` means a caller cancelling *us* does not. So:

        * inner task cancelled  -> the server is unreachable, report it;
        * we were cancelled     -> the caller stopped us, propagate and take the
          inner task down with us rather than leaking it.

        Without this, an unreachable MCP server raised ``CancelledError`` through
        ``discover_mcp_tools``'s ``except PlatformError`` and stopped the
        platform starting — the exact guarantee this package makes. Found by
        testing against a real server; a fake has no connect to fail.
        """
        task = asyncio.ensure_future(work)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if task.cancelled():
                raise self._transport_failure(operation, error) from error
            # The caller stopped us. Cancellation is never converted into a
            # result, and the inner task must not outlive the request.
            task.cancel()
            raise
        except Exception as error:
            raise self._transport_failure(operation, error) from error

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        """Open one initialised session, for the duration of one operation.

        A generator-based context manager, and that is load-bearing rather than
        stylistic. The SDK builds on anyio task groups, which must be entered
        and exited **in the same frame**; a hand-written ``__aenter__`` /
        ``__aexit__`` pair puts them in two, and anyio refuses with "Attempted
        to exit cancel scope in a different task than it was entered in". That
        was the first implementation, and a real server was what exposed it —
        it only shows up when the connect itself fails, which a fake has no way
        to reproduce.

        ``ClientSessionGroup`` is the SDK's own supported client. Driving the
        transport directly was the attempt before that, and it required an
        ``httpx2.AsyncClient`` — a vendored fork the SDK depends on and the
        platform deliberately does not.
        """
        async with ClientSessionGroup() as group:
            # Raises if the server is unreachable or refuses the handshake. The
            # caller wraps the whole block, so that failure becomes a
            # ProviderError naming the server rather than a raw anyio error.
            yield await group.connect_to_server(
                StreamableHttpParameters(
                    url=self._url,
                    headers=dict(self._headers) or None,
                    timeout=self._timeout_seconds,
                    sse_read_timeout=self._timeout_seconds,
                )
            )

    def _transport_failure(self, operation: str, error: BaseException) -> ProviderError:
        """Wrap a transport failure in a platform error.

        ``BaseException``, not ``Exception``, and that is not overreach. A
        failed connect surfaces from anyio as a **BaseExceptionGroup** — which
        derives from ``BaseException`` and so slips straight past
        ``except Exception``. It then escapes ``discover_mcp_tools``'s
        ``except PlatformError`` too, which would let an unreachable
        third-party server stop the platform from starting. That is precisely
        the guarantee this package makes, and a fake session could never have
        caught it breaking, because a fake has no connect to fail.

        Caller cancellation is handled before this is reached, by a preceding
        ``except asyncio.CancelledError: raise``. The discriminator is that a
        *bare* ``CancelledError`` is the caller stopping us, whereas a group is
        anyio unwinding its own scopes around a failed connect.

        That rule is a judgement, not a proof. If a caller cancels at the exact
        moment the SDK is unwinding, the cancellation can arrive inside the
        group and be reported as a transport failure instead. The consequence is
        a tool result saying the server was unreachable on a turn that was being
        abandoned anyway. ``asyncio.Task.cancelling()`` was tried as a sharper
        test and is not one: anyio cancels *this* task while tearing down, so it
        reads as caller cancellation whenever the server is simply down.

        The URL is not in the message. It may carry a token in a query string,
        and an error message reaches logs, telemetry and — through the tool
        result — sometimes a model.
        """
        _logger.warning(
            "mcp.server_unreachable",
            server_id=self._server_id,
            operation=operation,
            error_type=type(error).__name__,
        )
        message = (
            f"MCP server {self._server_id!r} could not complete {operation} "
            f"({type(error).__name__})."
        )
        return ProviderError(message, provider_id=f"mcp:{self._server_id}")


def _text_of(result: Any) -> str:  # noqa: ANN401 - SDK type, deliberately not leaked
    """Join the text content blocks of a result.

    Non-text content — images, embedded resources — is dropped rather than
    described. A model that receives ``[image]`` learns nothing it can use, and
    the platform has no vision path for tool output yet. When it does, this is
    where that changes.
    """
    parts = [
        block.text
        for block in getattr(result, "content", None) or []
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    return "\n".join(parts)


def _structured_of(result: Any) -> dict[str, Any] | None:  # noqa: ANN401 - SDK type
    """Return the structured result, when the server produced a mapping."""
    structured = getattr(result, "structured_content", None)
    return dict(structured) if isinstance(structured, dict) else None
