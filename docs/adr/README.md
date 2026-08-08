# Architecture Decision Records

Every major design decision is recorded here (`CLAUDE.md`, "Documentation
Standards"; `architecture.md` §79).

An ADR captures *why* a decision was made, what else was considered, and what it
costs — the context that is obvious while deciding and lost within months.

## Index

| ADR | Title | Status | Milestone |
| --- | --- | --- | --- |
| [0001](./0001-python-version-and-toolchain.md) | Target Python 3.12 and standardise on uv | Accepted | 01 |
| [0002](./0002-typed-configuration-and-fail-fast-startup.md) | Strongly typed configuration validated at startup | Accepted | 01 |
| [0003](./0003-workspace-layout-and-package-boundaries.md) | uv workspace with three Python packages | Accepted | 01 |
| [0004](./0004-provider-abstraction-via-protocols.md) | Declare provider contracts as `typing.Protocol` | Accepted | 01 |
| [0005](./0005-opentelemetry-first-observability.md) | OpenTelemetry-first observability | Accepted | 01 |
| [0006](./0006-llm-gateway-and-provider-neutral-contract.md) | Route every model call through an LLM Gateway | Accepted | 01 → 01.5 |
| [0007](./0007-task-runner-and-git-hook-strategy.md) | Task as the command runner; hooks share the project's tool versions | Accepted | 01.5 |
| [0008](./0008-server-sent-events-for-streaming-chat.md) | Stream chat over server-sent events, consumed with `fetch` | Accepted | 02 |
| [0009](./0009-agent-runtime-and-workflow-engine-abstraction.md) | An Agent Runtime, with LangGraph behind a workflow abstraction | Accepted | 03 |
| [0010](./0010-tool-framework-and-internet-search.md) | A tool framework, with the loop in the workflow layer | Accepted | 04 |

## Writing one

Copy [`0000-template.md`](./0000-template.md) to the next number and fill it in.

**When an ADR is required.** Any decision that is expensive to reverse: a
framework or library choice, a boundary between layers, a data contract, an
authentication approach, a deployment topology. If reversing it would touch many
files or require a migration, write one.

**When it is not.** Choices that are cheap to change — a helper's name, a log
message, an internal refactor within one module.

**Rules.**

1. **ADRs are immutable once accepted.** To change a decision, write a new ADR
   and mark the old one `Superseded by ADR-XXXX`. Editing history hides the fact
   that the decision changed, which is usually the most useful thing to know.
2. **List real alternatives.** An ADR with one option records a decision nobody
   actually made.
3. **State the costs.** The Negative section is not optional. Every real decision
   has one, and a reader evaluating whether the decision still holds needs to
   know what it was.
4. **Say how it is enforced.** The Compliance section names the test, lint rule
   or CI gate that will notice when the decision stops being honoured.
