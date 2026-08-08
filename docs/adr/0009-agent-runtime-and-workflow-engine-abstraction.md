# ADR-0009: An Agent Runtime, with LangGraph behind a workflow abstraction

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 03 — Agent Runtime and LangGraph

## Context

Milestone 02 shipped a working chat feature in which `ChatService` loaded
memory, assembled a prompt and called the gateway itself. That is the correct
amount of structure for one caller and the wrong amount for two: a scheduled
agent, an agent-to-agent call or a queue consumer would each have re-implemented
the same three steps, and the third copy is where they start to differ.

`architecture.md` §9 names the answer — an Agent Runtime owning the request
lifecycle — and §12 names a Workflow Engine beneath it. This milestone builds
both, and the interesting decisions are about where responsibility sits and how
much of LangGraph is allowed to be visible.

## Decision

### The runtime owns the lifecycle; agents only reason

Memory retrieval, prompt resolution, model selection, budget enforcement,
telemetry, event publication and memory update all moved into `AgentRuntime`.
`ChatAgent` is 130 lines and does four things: render a prompt, assemble
messages, call the gateway, translate the answer.

The rule is stated in the `Agent` protocol's docstring as a list of things an
agent must *not* do, because that is the form the rule actually gets broken in.
Each of those, done inside an agent, is done once per agent — and "God Agents",
which `CLAUDE.md` warns against, begin with exactly one convenience added in the
wrong place.

### `prepare()` and `execute()` are separate

The runtime splits a turn into preparation and execution. Everything that can
fail cheaply — unknown agent, disabled agent, missing prompt, missing prompt
variable — happens in `prepare()`, before a caller opens a stream.

This is the same constraint ADR-0008 found in the service layer, one level down:
once a `StreamingResponse` exists, the 200 is committed and no status code is
left to carry a failure. Having discovered it once, the runtime was built with
the split rather than acquiring it after a bug.

### LangGraph is confined to one module

`LangGraphWorkflowEngine` is the only file that imports LangGraph — the same
containment rule the provider packages follow for vendor SDKs (ADR-0006),
applied to orchestration. Its `TypedDict` state never leaves the module.

The graph has one node today. That is honest about the requirement and still
worth building, because the *shape* is what Milestone 04 needs: tool planning,
tool execution, evaluation, a reviewer agent and a human approval gate all attach
to this graph, and the runtime's call site does not change when they do.

### A second engine exists to prove the abstraction

`DirectWorkflowEngine` runs an agent by calling it. Twenty lines, no framework.

An interface with exactly one implementation is indistinguishable from that
implementation's API. The second one — written against the same protocol, sharing
no code — is what demonstrates the seam is real. Both are tested against one
parametrised suite, so a future engine inherits the whole contract rather than
acquiring its own partial one.

It is also a diagnosis tool: `PLATFORM_WORKFLOW__ENGINE=direct` runs the platform
with no graph library involved.

### Streaming bypasses the graph, and says so

LangGraph streams *state updates between nodes*, not tokens from within one.
Routing tokens through it would mean buffering the whole answer in a node and
emitting it as a single update — the precise thing streaming exists to avoid.

The adapter therefore delegates streaming to the agent and documents why, rather
than appearing to stream. When the graph becomes multi-node, per-node streaming
is a real design question; pretending to have solved it now would hide that.

### Prompts became versioned files

The system prompt moved from a constant in `settings.py` to
`prompts/agents/chat/system.md`, with YAML front matter and a version. An agent
pins a version for reproducibility; the runtime resolves it. Rendering is
substitution only — deliberately not Jinja2, because a template language is a
small programming language, and prompt files exist precisely so that they are
not code.

### Budget breaches are reported, not enforced by discarding work

A turn that exceeds its token or cost ceiling still returns its answer. The work
is done and paid for; discarding it would waste the spend *and* deny the user the
result. The breach is logged and published as an event. Real enforcement needs a
point where a loop can still be stopped, which arrives with tool calling in
Milestone 04 — the seam (`_enforce_pre_execution_budget`) exists and is empty.

## Alternatives Considered

### No runtime — keep orchestration in `ChatService`

**Rejected because:** it works until the second entry point, and the second entry
point is Milestone 04's tool loop. The refactor would then land entangled with a
feature, which is the worst time to move a boundary.

### LangGraph called directly from the runtime

**Rejected because:** it puts a third-party graph model in the middle of the
platform's core. LangGraph is young and its API moves; replacing it later would
mean touching the runtime, every agent, and every test that exercises
orchestration. The seam costs one protocol and one adapter.

### A multi-agent `execute(agents, ...)` signature now

**Rejected because:** it invents a shape before the requirement. Whether the unit
of work is a list, a graph, or a named workflow resolved from a registry is
determined by what multi-agent collaboration actually needs, and guessing now
means either rework or living with a wrong guess.

### Agents resolving their own prompts and memory

**Rejected because:** it is one convenience per agent, and the second agent does
it differently. It also makes an agent untestable without a filesystem and a
memory backend.

### Enforcing budgets by aborting the turn

**Rejected because:** the tokens are already spent when the ceiling is detected.
Aborting converts a cost overrun into a cost overrun *plus* a failed request.

## Consequences

### Positive

- A second entry point — scheduled, queued, agent-to-agent — reuses the whole
  lifecycle rather than re-implementing three steps of it.
- Adding an agent is a descriptor plus a prompt asset. No change to the runtime,
  the gateway, or any existing agent.
- The graph library is replaceable, and the parametrised engine suite proves it
  rather than asserting it.
- Startup refuses to run an agent naming a model no provider serves, so a typo in
  `PLATFORM_AGENT__MODEL_ID` is a boot failure with a clear message instead of a
  provider error on a user's first request.
- Prompts are versioned, pinnable and reviewable without a code deployment.

### Negative

- More indirection. A chat turn now passes through service → runtime → engine →
  agent → gateway → provider. Each boundary is justified above, but a developer
  tracing a call reads five files.
- The LangGraph graph has one node and compiles per execution. Both are fine at
  this size and both are wrong at some larger size; neither has been measured.
- Streaming does not go through the graph, so a future multi-node workflow will
  need a real answer to per-node streaming that this milestone did not have to
  give.
- Budget enforcement is advisory. A runaway cost is visible but not prevented
  until Milestone 04.
- `prompts/` must be deployed with the application. This was found by the
  integration tests, not by design — see the milestone record.

### Neutral

- `RuntimeTurn` is a plain class rather than a model: it holds a live `Agent`,
  which is not serialisable and has no business being validated.
- The model registry is populated at startup by asking providers, not from
  configuration, so it cannot advertise a model nothing can serve.

## Compliance

- `tests/unit/workflow/test_workflow_engines.py` runs one suite against both
  engines, and asserts they produce identical results and identical streams.
- `tests/unit/runtime/test_agent_runtime.py` covers lifecycle ordering, context
  propagation, prompt pinning, memory coordination and failure paths — including
  that a `ProviderError` survives the graph unchanged.
- `tests/unit/prompts/test_prompts.py` loads the repository's real prompt assets,
  so a malformed committed prompt fails the suite rather than the application.
- `tests/unit/dependencies/test_container.py` asserts `ChatService` holds a
  runtime and no gateway.
- `mypy --strict` checks every implementation against its protocol at the point
  of registration in the composition root.

## References

- `architecture.md` §9 Agent Runtime, §12 Workflow Engine, §14 Agent Lifecycle, §17 Agent Descriptor, §26 Registries, §34 Prompt Registry
- [ADR-0006](./0006-llm-gateway-and-provider-neutral-contract.md) — the gateway agents call
- [ADR-0008](./0008-server-sent-events-for-streaming-chat.md) — where the prepare/execute split was first forced
