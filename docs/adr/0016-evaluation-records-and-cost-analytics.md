# ADR-0016: Evaluation records, and cost analytics as an evaluation sink

- **Status:** Accepted
- **Date:** 2026-08-09
- **Deciders:** Platform architecture
- **Supersedes:** nothing
- **Related:** [ADR-0005](0005-opentelemetry-first-observability.md) (observability),
  [ADR-0013](0013-policy-driven-model-routing.md) (routing)

---

## Context

`CLAUDE.md` is unusually specific here: *"Every model invocation should generate
evaluation metadata"*, and lists what it must capture — provider, model,
latency, tokens, estimated cost, success. It also asks the architecture to
support cost dashboards by provider, model, agent and user.

`EvaluationRecord` and `EvaluationProvider` had existed in the SDK since
Milestone 01 for exactly this. Nothing produced a record and nothing consumed
one. This ADR records closing that loop.

## Decision

### The runtime emits one record per turn, to one port

`AgentRuntime` records after every turn — completed, failed, or streamed — to a
single `EvaluationProvider`. It does not know how many sinks exist.

### Failed and abandoned turns are recorded too

This is the decision most likely to be got wrong by accident, because recording
only successes is the path of least resistance.

Data that counts only successful turns flatters the platform *precisely when it
is misbehaving*: an incident where every second request fails would show
unchanged cost and improving latency. And a failed turn frequently consumed
tokens, which were billed.

Streaming is recorded in a `finally`, so a turn the user abandoned is still
counted. **When** that happens is worth stating, because the obvious reading is
wrong: breaking out of an `async for` does not run the block — closing the
generator does, which is what the SSE layer and `async with` do. This was
measured, not assumed; the count is unchanged immediately after a `break` and
increments on `aclose()`. An earlier comment claimed the abandoned turn was
measured without saying when, and a live run caught the overclaim.

### Cost analytics is an `EvaluationProvider`, not a special case

`InMemoryCostAnalytics` implements the same interface and, instead of writing a
record somewhere, adds it to counters an endpoint can read.

That is what lets the runtime record once. `CompositeEvaluationProvider` fans out
to as many sinks as the composition root registers, so adding Application
Insights or Cosmos DB later is a line in a tuple and nothing else moves.

### Attribution follows the routing decision

The record carries `turn.routing.provider_id` and `turn.routing.model_id`, not
the agent's configured ones. With policy routing those can differ, and cost
attributed to a model that did not answer is worse than no attribution — it is
wrong in a way that looks right.

### Telemetry may never fail a request

Every `record` implementation catches everything. That is a rule this codebase
otherwise treats with suspicion, and it is correct exactly here: losing one
measurement is invisible to a user; losing their answer because a sink hiccupped
is not. The composite enforces it rather than trusting each sink to.

The logging provider does not even log its own failure — the logger is the thing
that just failed. It counts drops and reports them in its health detail instead.

### Records carry no conversation content

No prompt, no completion, no user input. A record is counts, identifiers and
money. It is exported to systems with different retention and access rules than
the conversation, and the moment it carries content it becomes a second copy of
user data nobody is governing.

### Money is `Decimal` end to end

Fractions of a cent summed over many requests are exactly where binary floating
point drifts. Prices are `Decimal`, totals are `Decimal`, and the log renders
the string rather than a float — otherwise the error is reintroduced at the last
step.

## Consequences

### Good

- Every invocation is measured, including the ones that failed.
- `GET /api/v1/analytics/costs` answers "what is this costing, and which model
  is responsible?" with no new resource provisioned.
- Adding a durable sink is a one-line change in the container.
- Cost is attributable to model, provider and agent — the three groupings an
  operator actually acts on.

### Bad, or at least costly

- **Totals are per-process and reset on restart.** This is a live gauge, not a
  ledger. The ledger is the evaluation records in the structured log, which
  survive restarts and aggregate across replicas. The endpoint's response says
  so in a `scope` field rather than in documentation, because a per-replica
  figure read as platform-wide spend is the easiest way to make a cost dashboard
  actively misleading.
- **The endpoint has no authorisation.** Spend by model and agent is
  commercially sensitive, and this is as open as the rest of the API.
  `CLAUDE.md` defers authorisation, so this follows — but it is the endpoint
  that will need it first, and the runbook says so.
- **`average_latency_ms` is a mean.** It says nothing about the tail, which is
  what users notice. Percentiles need the individual records; the logs keep
  them.
- **Cost is an estimate.** Computed from configured prices, never from an
  invoice. A model with no pricing configured contributes zero rather than a
  guess — which is honest, and means an unpriced model silently reads as free.
- **No time series.** "Cost today versus yesterday" is not answerable here. That
  needs a durable sink, which is the next implementation rather than a change to
  this one.

## Alternatives considered

**Derive analytics by querying the logs.** Durable, cross-replica, already
written. Rejected as the *only* answer because it needs a log analytics backend
configured and a query language to use it — which makes the first question an
operator asks unanswerable on a laptop. The two coexist: the log is the record
of truth, this is the gauge.

**A dedicated metrics/analytics service interface separate from
`EvaluationProvider`.** Rejected: the runtime would then record twice, to two
ports, with two chances to diverge. One port and a composite keeps the runtime
ignorant of how many things listen.

**OpenTelemetry metrics instead of counters.** Genuinely the right long-term
answer for aggregation, and ADR-0005 already commits to OTel. Rejected for
*this* slice because a metrics pipeline needs a collector and a backend to be
readable at all, whereas the requirement was to make cost visible now. The
record shape is unchanged by adding an OTel sink later.

**Record only successful turns.** Simpler, and wrong for the reasons above.
