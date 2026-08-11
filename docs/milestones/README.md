# Platform Git Milestone Structure

## Repository
`multi-agent-ai-platform`

## Purpose
Track reusable, business-neutral capabilities required by enterprise agentic solutions.

## Milestones

| Milestone | Scope | Outcome |
|---|---|---|
| M10 | Enterprise Workflow Foundation | Durable workflow/checkpoint primitives |
| M11 | Approval, Events, Tool Authorization | Reusable approval, event/job, authorization and idempotency primitives |

## Rules
1. Keep the platform business-neutral.
2. Do not add Internal Fitments entities or states.
3. Preserve the provider-neutral LLM contract and LLM Gateway.
4. New capabilities must be reusable beyond Internal Fitments.
5. Avoid premature microservices.
6. Include tests and documentation/ADRs.
7. Do not commit/push unless explicitly requested.

## Dependency
M10 → M11 → Internal Fitments consumption.
