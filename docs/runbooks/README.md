# Runbooks

Operational procedures for diagnosing and resolving production incidents.

## Available

| Runbook | Covers |
| --- | --- |
| [Azure AI Foundry setup](./azure-ai-foundry-setup.md) | Connecting a deployment, RBAC, keyless auth, scale-to-zero, troubleshooting |
| [Search providers](./search-providers.md) | Choosing a search backend, Tavily keys, cost control |

## Not yet populated

There is no production deployment yet, so there is little to operate. The rest
land with the systems they cover:

| Runbook | Milestone |
| --- | --- |
| Deployment and rollback | 07 |
| Provider outage — failover and degraded operation | 08 |
| Cost spike investigation | 08 |
| Latency regression triage | 08 |
| Secret rotation | 08 |
| Incident response and escalation | 08 |

Writing a runbook for a system that does not exist produces a document that is
wrong on the day it is first needed.

## What a runbook must contain

1. **Symptom** — what an operator observes: the alert, the dashboard, the user
   report.
2. **Impact** — who is affected and how badly. Determines urgency.
3. **Diagnosis** — concrete commands and queries, in order, with what each result
   means.
4. **Resolution** — the fix, with the exact commands.
5. **Rollback** — how to undo the fix if it makes things worse.
6. **Escalation** — who to involve, and at what point.
7. **Prevention** — the follow-up that stops a recurrence.

Written for someone woken at 03:00 who did not build the system. Every command
copy-pasteable; no step that assumes context.

## Diagnosis starts with the correlation ID

Every request carries one, returned in `X-Correlation-ID` and present on every
log record and span. A user quoting that ID gives an operator the complete
server-side history of exactly what they experienced — which is the point of
building it into Milestone 01 rather than adding it under pressure later.
