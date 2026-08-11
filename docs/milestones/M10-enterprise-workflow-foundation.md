# M10 — Enterprise Workflow Foundation

## Objective
Provide reusable durable workflow primitives for long-running enterprise agentic business processes.

## Scope
- Workflow instance/execution
- State and version
- Transition
- Task
- Checkpoint/resume
- Retry/timeout/cancellation/recovery
- Correlation ID
- Idempotency key

## Non-Scope
No Internal Fitments domain models, states, calendar, staffing or notification logic.

## Acceptance Criteria
- Durable state/checkpoint and resume
- Explicit retry/timeout semantics
- Recovery/cancellation support
- Observability/correlation
- Idempotency support
- No business-specific concepts
- Tests and architecture/ADR updates
