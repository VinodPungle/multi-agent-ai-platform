# ADR-0010: A tool framework, with the loop in the workflow layer

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 04 — Internet Search and Tool Framework

## Context

Milestone 03 left a runtime that could reason but not act. Adding the first tool
is less about the tool than about the shape of everything after it: GitHub, Jira,
SQL, SharePoint and eventually MCP servers all arrive through whatever seam this
milestone establishes.

`architecture.md` §33 fixes the pipeline — `Agent → Runtime → Tool Registry →
Tool → Runtime → Agent` — so the open questions were where the *loop* lives, what
a tool is allowed to fail with, and which search backend can be shipped honestly.

## Decision

### One executor, and it never raises

`ToolExecutor` resolves the tool, checks the agent declared it, validates
arguments, applies the descriptor's timeout and retry policy, records telemetry
and publishes events. Every outcome — unknown tool, denied tool, bad arguments,
timeout, a tool that threw — becomes a `ToolResult` with `succeeded=False`.

This is the LLM Gateway's argument (ADR-0006) one layer across: timeout, retry,
authorisation and auditing are identical for every tool, and implemented per tool
they would be written once per integration and drift immediately.

The never-raises rule is the part worth defending. A failing tool is usually
something the agent should reason about — "the search is down, answer from what
you know" is a better outcome than a 502 — and an exception discards a turn the
user has already waited for.

### The agent's declaration is the authority on what it may call

A model can emit any tool name, including one inferred from the conversation.
The executor refuses anything outside `descriptor.tool_ids`. Without that,
registering a destructive tool for one agent would make it reachable by every
agent that could be persuaded to name it.

### The loop lives in the workflow layer, shared by both engines

`run_tool_loop` is one algorithm called by both `DirectWorkflowEngine` and
`LangGraphWorkflowEngine`. Orchestration is the engines' job, so the loop belongs
to them — but the loop itself is one piece of logic, and two copies would be two
places for an off-by-one in the iteration bound.

The LangGraph engine still has one node, with the loop inside it rather than as
`agent → tools → agent` edges. That is a staging decision, stated plainly: making
it edges now would mean two implementations of the loop before anything needs
them to differ. When a second agent joins the graph, the loop becomes edges.

### Budget enforcement finally became real

Milestone 03 could only report a breach after the fact, and said so. A loop
changes that: `max_tool_invocations` and `max_model_calls` are checked *between*
iterations, where stopping still saves the next call. An agent with no budget
gets a default ceiling of five model calls, because an unbounded loop turns one
request into an open-ended bill.

When the ceiling is hit, the model's last message is a tool request rather than
an answer, so the loop substitutes a plain explanation — returning the raw result
would show the user a blank reply.

### Two search providers, and the real one is keyless

`MockSearchProvider` answers offline and deterministically, which is what CI and
a laptop without connectivity need. `DuckDuckGoSearchProvider` performs a real
internet search through the Instant Answer API.

DuckDuckGo was chosen for one reason above all: **no API key**, so
`docker compose up` gives working internet search with no signup — which is what
"local development first" actually requires.

Its limitation is documented rather than hidden. The Instant Answer API returns
abstracts and related topics, not ranked web results: excellent for "the eiffel
tower", nearly useless for "best python profiler 2026". A keyed provider (Brave,
Tavily, Bing) is a new adapter in `agent_platform.search` plus configuration —
the tool, the runtime and every agent are unaffected.

### The mock model really calls the tool

`MockLLMProvider` emits a `ToolCall` when the user's words ask for a lookup, and
composes a cited answer when a tool result is present. That makes the whole loop
exercisable end to end, deterministically, with no API key — and it is what
caught the query-stripping defect below.

## Alternatives Considered

### The loop in the runtime

**Rejected because:** the runtime's job is the request lifecycle, and
orchestration is explicitly the workflow engine's (`architecture.md` §12). Putting
the loop in the runtime would mean the engine abstraction no longer described the
thing that actually orchestrates.

### The loop as LangGraph nodes now

Attractive, and where this ends up.

**Rejected for now because:** it forces a second implementation for the direct
engine before anything needs them to differ, and the parametrised engine suite
would then be testing two loops rather than one contract.

### Tools raising exceptions instead of returning failed results

**Rejected because:** it makes every tool failure fatal to a turn. The agent is
usually the right place to decide whether a failed lookup is recoverable, and it
cannot decide anything about an exception that unwound past it.

### A keyed search provider as the default

**Rejected because:** it would make the documented local setup depend on a signup
and a secret. The abstraction means adding one later costs an adapter.

### JSON Schema validation via a library

**Rejected for now because:** the one tool's schema has two properties, and a
validation dependency to check them would be more machinery than the thing it
checks. The comment in `validate()` names the point at which that reverses.

## Consequences

### Positive

- Adding a tool is a `ToolProvider` implementation plus a registration line.
  Timeout, retry, authorisation, telemetry and failure handling come for free.
- A tool cannot break a turn, whatever it does.
- Budgets are enforced where enforcement still saves money.
- Internet search works out of the box with no key, and a keyed provider is a
  configuration change away.
- The search feature flag is a real off switch: with it off the tool is not
  registered, so a turn costs exactly one model call.

### Negative

- **Streaming does not use tools.** The streaming path streams the agent
  directly, so a streamed chat turn cannot call a tool. `CompletionChunk` has no
  way to carry a tool call, and inventing one before a real provider's streaming
  tool protocol is known would mean guessing. The non-streaming endpoint has the
  full capability; the frontend uses the streaming one. **This is the milestone's
  most significant limitation.**
- The LangGraph graph still has one node, so the graph is not yet doing the
  orchestration the tool loop needs.
- Tool arguments are validated by hand rather than against the declared schema,
  so the schema and the check can drift.
- The DuckDuckGo backend answers encyclopaedic questions well and current-events
  questions poorly, which will mislead anyone who assumes "internet search" means
  ranked web results.

### Neutral

- The tool exchange (the assistant's request and the tool results) is not stored
  in conversation memory. History is the conversation; tool traffic is execution
  detail, and storing it would spend context replaying it on every later turn.

## Compliance

- `tests/unit/tools/test_tool_executor.py` — 18 tests, every one a variation on
  "this does not raise".
- `tests/unit/tools/test_internet_search.py` — provider parsing against payload
  shapes the live API produces, tool validation, the loop end to end, and the
  loop's bounds driven by an agent that never stops asking for tools.
- Two tests hit the live API, marked `integration`, asserting on shape rather
  than content.
- `uv run pytest -m "not integration"` excludes all network access.

## References

- `architecture.md` §32 Tool Registry, §33 Tool Execution, §37 Search Provider
- [ADR-0006](./0006-llm-gateway-and-provider-neutral-contract.md) — the same containment argument for providers
- [ADR-0009](./0009-agent-runtime-and-workflow-engine-abstraction.md) — the runtime and engines this extends
