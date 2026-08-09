# ADR-0013: Policy-driven model routing

- **Status:** Accepted
- **Date:** 2026-08-09
- **Deciders:** Platform architecture
- **Supersedes:** nothing
- **Related:** [ADR-0006](0006-llm-gateway-and-provider-neutral-contract.md)
  (gateway and resolver), [ADR-0009](0009-agent-runtime-and-workflow-engine-abstraction.md)
  (runtime lifecycle)

---

## Context

`CLAUDE.md` is explicit: *"Never hardcode a model. Model selection should
support per agent, per request, per user, per workflow. The runtime should allow
policy-based selection."*

Until now the runtime read `descriptor.model_id` and used it. That satisfies
"per agent" and nothing else. The seam existed — `AgentRuntime.prepare` was the
one place a model was chosen — but nothing occupied it.

Two things made the gap worth closing beyond ticking an acceptance criterion:

1. **A capability mismatch was undetectable.** An agent configured with tools
   pointed at a model that cannot call them does not error. It answers, without
   using the tools, and the answer looks fine. That is a wrong answer rather
   than a failure, which is the worse of the two.
2. **The provider resolver ignored `model_id` entirely.** Correct while one
   provider was registered; false the moment anything could choose otherwise.

## Decision

### A chain of narrowing policies, not a scoring function

Routing runs an ordered chain over the model catalogue. Each policy filters,
reorders, or both.

A weighted score was the obvious alternative and is what most routing libraries
do. It was rejected on operability. When a scored router picks a model an
operator did not expect, the answer to *"why?"* is a number, and the only way to
change the outcome is to guess at weights. A chain answers with the name of the
step that removed the alternative — `capability`, `context-window`,
`availability` — which is something a person can act on.

### Constraints and rankings are different things

**Constraints** remove models that *cannot* serve the turn. An empty result is a
real failure and the router names the policy responsible.

**Rankings** reorder models that could all serve it, and never remove anything.

This distinction is load-bearing. Without it, asking for the cheapest model
could produce "no model available" — an objective silently behaving as a second
constraint, which is exactly the kind of surprise that makes operators stop
trusting a routing layer and pin everything.

### `balanced` is the default, and it honours configuration

The default objective puts the agent's configured model first whenever it is
still viable. An agent's model is an explicit decision by whoever wrote it, and
overriding it silently is worse than a marginally higher bill. `lowest_cost`,
`largest_context` and `highest_capability` are opt-in, and every decision they
produce records that they were asked for.

### The decision explains itself

`RoutingDecision` carries the policy that chose, a human reason, and every model
considered in ranked order. It goes onto the ExecutionContext, so telemetry,
cost attribution and the evaluation record all join on the model that *actually
answered* rather than the one that was configured.

The runner-up list is deliberate: when a choice looks wrong, the second-place
model is usually the single most informative thing available.

### Provider resolution follows the model

`ConfiguredProviderResolver` was replaced by `RegistryBackedProviderResolver`,
which looks a model up in the catalogue and returns the provider that
advertised it. Without this, routing would be decorative — a decision to use a
model on a second provider would resolve to the default provider, which would be
asked for a model it had never heard of.

The old resolver was **deleted, not kept alongside**. Two implementations where
only one is wired is how a stale one drifts out of agreement with reality
unnoticed — which is precisely what this change caught elsewhere (below).

### Pinning is a runtime parameter, not an API field

`prepare(pinned_model_id=...)` exists for workflows and operator tooling. It is
deliberately **not** exposed on the public HTTP API: choosing a model is
choosing a bill, and there is no authorisation layer yet to decide who may.
`CLAUDE.md` defers authorisation; this defers the surface that would need it.

## Consequences

### Good

- Models are selectable by policy, per agent and per request, by configuration.
- A tool-using agent can no longer be routed to a model that cannot call tools.
- A turn too large for a model is refused before the prompt is sent and billed.
- Routing across providers works, because resolution follows the catalogue.
- Every decision is reproducible from its inputs and explicable from a log line.

### Bad, or at least costly

- **Routing sits in the path of every turn.** It is pure in-memory filtering
  over a handful of descriptors, so the cost is negligible — but it is now a
  component that can refuse a request, and a misconfigured catalogue fails
  closed. That is the intended trade and it is still a new failure mode.
- **Capability declarations now matter.** A provider that under-declares makes
  its model unroutable. This surfaced immediately: `MockLLMProvider` emitted
  tool calls while `supports()` and `list_models()` both denied it — a stale
  claim from before tool calling existed, invisible because nothing read it.
  Both providers now compute capabilities once, and a test asserts the two
  answers agree.
- **The context estimate is a rule of thumb.** Four characters per token, with
  no tokenizer. It errs towards under-estimating, which keeps a marginal model
  rather than excluding a workable one — the first failure is reported by the
  provider, the second would be invisible.
- **`highest_capability` is an approximation and named as one.** Breadth of
  declared capabilities, because the platform has no quality score. Deriving one
  from price would encode "expensive means good".

### Neutral

- The chain is fixed in the composition root; only the objective is
  configurable. Making the chain itself configuration would let a deployment
  remove a constraint, which is the one thing it must not be able to do by
  accident.

## Alternatives considered

**Leave selection on the descriptor and call it configuration.** Defensible, and
what the platform did. It satisfies "per agent" only, and it cannot express "use
the cheap model for this workflow" or refuse a capability mismatch.

**Weighted scoring across cost, latency and quality.** More expressive, far less
operable. Rejected above. It also needs latency and quality data the platform
does not collect; inventing them would make the router confidently wrong.

**Route inside the gateway.** Fewer moving parts — the gateway already resolves
providers. Rejected because the gateway is deliberately about *how* a call is
made, not *what* is called: putting selection there would mean the runtime no
longer knows which model it asked for, and the ExecutionContext would be stamped
with a model chosen after the fact.

**Automatic failover to a second model on error.** Explicitly refused, and the
prohibition is inherited from ADR-0006. Silent substitution changes which model
answered a user with nothing in the request recording it, and makes evaluation
data incomparable. Withdrawing a model with `is_available` does the same job
where the decision is visible and attributable.
