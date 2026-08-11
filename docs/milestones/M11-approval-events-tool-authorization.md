# M11 — Approval, Events and Tool Authorization

## Objective
Provide reusable enterprise primitives for human approval, background/event processing, tool authorization and side-effect safety.

## Scope
### Approval
Approval request/ID, approver, status, approve/reject, timeout/escalation metadata, audit/correlation.

### Events and Jobs
Event ID/type, correlation/causation IDs, timestamp, retry, timeout, dead-letter, replay/recovery.

### Tool Authorization
Capabilities: READ, WRITE, SIDE_EFFECTING, ADMINISTRATIVE. Authorization is enforced outside the LLM.

### Idempotency
Idempotency key, duplicate detection, existing-result retrieval.

## Non-Scope
No Internal Fitments-specific approvals/events/tools/calendar/staffing/notifications.

## Acceptance Criteria
Generic approval, event/job retry/recovery, authorization, idempotency and tracing work without provider coupling.
