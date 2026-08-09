# ADR-0014: MCP tools as a Tool Registry adapter

- **Status:** Accepted
- **Date:** 2026-08-09
- **Deciders:** Platform architecture
- **Supersedes:** nothing
- **Related:** [ADR-0010](0010-tool-framework-and-internet-search.md) (tool framework),
  [ADR-0004](0004-provider-abstraction-via-protocols.md) (protocols)

---

## Context

`CLAUDE.md` states the requirement and the constraint together:

> The platform should be compatible with the Model Context Protocol (MCP). **Do
> not tightly couple tools to MCP.** Instead, design the Tool Registry so tools
> can be backed by local implementations, REST APIs, Azure Functions or MCP
> servers. Future additions should require only a new adapter.

ADR-0010 built the tool framework with that in mind. This ADR records what
happened when the claim was tested: whether MCP really did fit behind the
existing `ToolProvider` interface, or whether the interface had to move.

**It did fit.** The runtime, the tool executor, the tool loop, the workflow
engine and every agent are unchanged. An MCP tool is resolved through the
registry, validated, timed, retried, logged, traced and budgeted by exactly the
same code path as `internet-search`.

## Decision

### One adapter class, and a protocol the platform owns

`MCPTool` implements `ToolProvider` and wraps one remote tool. Below it sits
`MCPSession` — a three-method protocol the *platform* defines (`server_id`,
`list_tools`, `call_tool`), not the SDK's.

That indirection is not ceremony. It means the MCP SDK is imported by exactly
one module, so an SDK rename breaks one file loudly instead of leaking upward,
and it makes the adapter testable against a fake that is genuinely complete
rather than a convenient subset.

The renames are not hypothetical: `streamablehttp_client` became
`streamable_http_client` and `inputSchema` became `input_schema` at SDK 2.0.
Both were found by introspecting the installed package rather than writing from
memory of the older API.

### Streamable HTTP only

`stdio` is the other common transport, and it means spawning a subprocess inside
the container. That is a supply-chain and isolation decision, not an
integration, and it is refused at configuration time with an error saying so —
rather than being ignored, which would look like a server that had no tools.

### Discovery at startup, not per request

A tool's description is sent to the model so it can decide whether to call it.
Discovering per request would make the *prompt* vary with a third party's
deployment schedule, so two identical questions could get different answers for
reasons invisible in the request. It would also put a network round trip in
front of every turn.

The cost is that a tool added mid-run is not seen until a restart. The opposite
case — a tool that *disappeared* — is reported by the health check, because that
one produces failures rather than a missing capability.

### A dead server must not stop the platform

An MCP server is a third party. Refusing to start because someone else's service
is down would hand them an outage switch over a platform whose core function
does not depend on them. Discovery failures are logged loudly and skipped.

Configuration mistakes are treated differently and are *not* forgiven: MCP
enabled with no server, a duplicate `server_id`, or a non-HTTP URL all fail at
startup.

### Tool ids are namespaced by server

`mcp.<server_id>.<tool_name>`. Two servers each exposing `search` is ordinary,
and an unnamespaced collision would be resolved by whichever registered first —
silently, and differently depending on configuration order. Dots rather than
colons because the id also travels to models as a tool name, and several
providers reject names outside `[A-Za-z0-9_.-]`.

### Schemas are validated with a real validator

A local tool's schema is written by its author and can be checked in a few
lines; ADR-0010 said exactly that, and predicted the trade would reverse. An MCP
schema arrives from a server nobody here controls and can be arbitrarily deep.
`jsonschema` is the dependency that costs, and it is justified by the tool it
checks rather than by preference.

A malformed *schema* is treated as no schema: that is the server's bug, and
refusing every call because of it would disable a tool that may work perfectly.

### No retries

`RetryPolicy(max_attempts=1)`. A remote tool may have side effects the platform
cannot see, and the protocol carries no idempotency signal. `CLAUDE.md`: never
retry non-idempotent operations automatically.

### No authentication flow

Servers that need credentials get a configured header. The platform holds no
token of its own and performs no OAuth flow. Who consents, on whose behalf, with
what audit trail, is a governance decision — inventing one here would be
inventing authorisation, which `CLAUDE.md` defers.

## Consequences

### Good

- MCP servers become available to agents by configuration alone.
- Nothing in the runtime, the tool pipeline or any agent changed. The claim
  ADR-0010 made about the tool interface is now demonstrated rather than
  asserted.
- The SDK is confined to one module and covered by tests against a real server.

### Bad, or at least costly

- **A connection handshake per tool call.** Each operation opens a session,
  works, and closes. Tens of milliseconds against calls that already take
  hundreds — but it is a real cost, and pooling would be a second `MCPSession`
  implementation rather than a change to the adapter.
- **Nine transitive packages** arrive with the MCP SDK, several of them
  server-side (`sse-starlette`, `python-multipart`). That is the price of not
  hand-rolling a JSON-RPC client, and the trade favours the SDK.
- **Cancellation is disambiguated by construction, not by inspection.** See
  below; this was the hardest part of the work and the residual risk is real.
- **A third party's text becomes prompt material.** A server that describes its
  tools badly produces an agent that calls them badly, and the platform does not
  rewrite descriptions because doing so would mean inventing claims about a tool
  it did not implement.

### The cancellation problem, recorded because it will recur

When the server is unreachable, the SDK unwinds its anyio cancel scopes by
cancelling the running task, and what escapes is a bare
`asyncio.CancelledError`. That is **indistinguishable** from a caller cancelling
the request: measured on both paths, `Task.cancelling()` is `1` and
`Task.uncancel()` returns `0`.

The consequence, before it was fixed, was severe and quiet: an unreachable MCP
server raised `CancelledError` straight through `discover_mcp_tools`'s
`except PlatformError` and stopped the platform from starting — the exact
guarantee this ADR makes.

The fix is structural. Each SDK operation runs in its own task, awaited through
`asyncio.shield`:

- the inner task is cancelled → the SDK cancelled itself → the server is
  unreachable, report a `ProviderError`;
- this task is cancelled → the caller stopped us → propagate, and cancel the
  inner task so it cannot outlive the request.

Both branches are tested against a real server. The residual risk is a caller
cancelling at the exact moment the SDK is unwinding, which would be reported as
an unreachable server on a turn that was being abandoned anyway.

**None of this was reachable through a fake**, which has no connect to fail. It
is the clearest case yet for this project's rule that a double more convenient
than the real thing tests the double.

## Alternatives considered

**Hand-rolled JSON-RPC client.** No SDK, no transitive packages, full control.
Rejected: MCP has session negotiation, protocol versioning and streaming
semantics, and re-implementing them would be a maintenance liability that grows
with the spec.

**A long-lived pooled session.** Faster — no handshake per call. Rejected on
lifetime correctness: the transport is built on anyio task groups, which cannot
be entered in one task and exited in another, and application startup and
shutdown are different tasks. The failure mode is a hang, not an error. A pooled
session that dies with its server also stays dead.

**A dedicated `MCPToolProvider` interface separate from `ToolProvider`.**
Rejected, and this is the decision the whole ADR turns on: a second tool
interface would mean a second execution path, and every policy the runtime
applies — authorisation, timeout, retry, telemetry, budget — would need
implementing twice. `CLAUDE.md` asked for an adapter, and an adapter is what
keeps one pipeline.

**Discovering tools per request.** Fresher catalogue. Rejected because a tool
description is prompt input, and a prompt that changes with a third party's
deploys makes two identical questions answerable differently for reasons nobody
can see in the request.
