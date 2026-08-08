# ADR-0006: Route every model call through an LLM Gateway

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** Architectural refinement between Milestone 01 and Milestone 01.5

## Context

[ADR-0004](./0004-provider-abstraction-via-protocols.md) established `LLMProvider`
as a `typing.Protocol`, which makes a provider replaceable. It does not answer a
second question: *who* applies the behaviour that has to happen around every
model call regardless of provider.

That list is not short — request normalisation, response normalisation, provider
selection, retry, timeout, telemetry, cost estimation. Left unassigned, it lands
in one of two places, and both are wrong:

**In the provider.** Written once per vendor, so the second provider either
copies it or quietly diverges. Two providers then disagree about how many times
a call is retried, and the difference is invisible until an incident.

**In the runtime.** Orchestration acquires a second job. Every call site that
wants a model has to remember the policy, and "the runtime is provider
independent" survives only as long as nobody takes a shortcut.

`architecture.md` §30 names the answer — an LLM Gateway — and this ADR records
the decision to build it now, before there is a provider, rather than after.

There is a timing argument for doing it now specifically. Azure AI Foundry
arrives in Milestone 05. If it arrives before the gateway exists, the first
provider defines the shape of the call path, and the abstraction ends up being
described as "what Azure does, generalised" — which is the coupling this platform
exists to avoid. The seam is cheaper to build against zero providers than one.

## Decision

Introduce `LLMGateway` as the single path from business logic to any model.

**The contract lives in the SDK.** `agent_platform_sdk.interfaces.llm_gateway`,
a `@runtime_checkable` `Protocol`, consistent with ADR-0004. The runtime, agents,
workflows and evaluation depend on this name. `LLMProvider` becomes an
infrastructure-facing contract that only the gateway and the composition root
mention.

**The implementation lives in the backend.** `agent_platform.gateway`, which
imports the SDK and never `agent_platform.providers`. `import azure` in this
package would be as much a violation as it would be in the runtime.

**Responsibilities split at one line:**

| Gateway | Provider |
| --- | --- |
| Request normalisation and validation | Wire-format translation |
| Response normalisation | Transport and authentication |
| Provider selection | Tokenisation |
| Retry and timeout policy | Mapping vendor failures onto `PlatformError` |
| Telemetry, cost estimation | Nothing else |

**Provider selection is a separate port.** The gateway asks
`LLMProviderResolver`; it never holds a provider. `ConfiguredProviderResolver`
answers from the composition root today, a registry-backed resolver answers in
Milestone 03, and a policy-driven one can answer later — none of which the
gateway sees.

**The common request and response models are OpenAI-shaped.**
`CompletionRequest` gains `system_prompt`, `top_p`, `response_format` and
`metadata`; `CompletionResponse` gains `provider_metadata` and `model_metadata`,
completing the contract documented in `architecture.md` §30. Field names track
the OpenAI-style Chat API vocabulary deliberately: an adapter for any
OpenAI-compatible endpoint — Azure OpenAI, OpenAI, Ollama, vLLM, NVIDIA NIM, TGI
— is then a rename rather than a translation layer.

Four things are deliberately **not** decided here, because implementing them
without a second provider would be designing against an imagined requirement:
routing, failover, fallback models, and health-based provider exclusion. The
seam that will hold them is the resolver.

## Alternatives Considered

### Policy in a provider base class the adapters inherit

**Rejected because:** it reintroduces the inheritance ADR-0004 removed, and
because a base class can only apply policy the base class knows about. A vendor
adapter that needs to override one hook ends up overriding the template method
and silently dropping the telemetry inside it.

### Policy as decorators wrapped around each provider at registration

Genuinely close. `RetryingProvider(TracingProvider(AzureProvider()))` composes
well and needs no new interface.

**Rejected because:** the decorator chain is assembled per provider, so ensuring
every provider gets the same chain is a convention, not a structure — the second
provider is one registration line away from a different one. It also has nowhere
to put provider *selection*, which is not a property of any single provider, so
that would still need a component above the chain. Given that component has to
exist, folding the rest into it is one concept instead of two.

### Leave it to the runtime, and revisit when a second provider appears

**Rejected because:** "revisit later" means the refactor lands at the moment a
second provider is being added, which is the worst time — the change is then
entangled with a new vendor integration and both are hard to review. It also
means the Milestone 03 runtime would be written against `LLMProvider` and every
call site rewritten afterwards.

### A gateway that is itself a `Provider`

**Rejected because:** the gateway has no external dependency, no credentials and
no endpoint. `initialize()` and `health_check()` would be pass-throughs to
whatever sits behind it, and `provider_id` would be a fiction. Its health is the
health of the providers, which the health service already aggregates directly.

## Consequences

### Positive

- Retry, timeout, telemetry and cost estimation exist once and apply to every
  provider identically, including ones not yet written.
- The Azure AI Foundry adapter in Milestone 05 has a narrow job: translate and
  transport. It cannot accidentally define platform policy.
- Adding an OpenAI-compatible provider is a new class in
  `agent_platform.providers` plus one registration line. No business logic
  changes — the property this platform is built to have.
- Cost and latency are guaranteed present on every response, so the evaluation
  pipeline needs no per-provider special case.
- The gateway is fully testable with a fake provider, which is how it is tested:
  37 unit tests, no network, no vendor SDK.

### Negative

- One more indirection between an agent and a model. A developer tracing a call
  reads two files instead of one.
- The gateway is a component with no user until Milestone 03. It is exercised by
  tests rather than by traffic, so the first real integration may still surface
  something the fakes did not.
- `DefaultLLMGateway` narrows `stream()` to `AsyncGenerator` while the protocol
  declares `AsyncIterator`. Permitted, and it buys callers `aclose()`, but it is
  a difference between the contract and the implementation that a reader has to
  notice.
- Streaming is not retried at all. That is the correct default, but it means a
  provider that fails on its very first chunk — where a retry would in fact be
  safe — fails the request. Revisit if it proves common.

### Neutral

- `ResponseFormat` is declared and carried but not yet honoured; providers
  implement it from Milestone 05.
- Gateway policy is configured under `PLATFORM_LLM_GATEWAY__*` with documented
  defaults, so no deployment has to set anything for behaviour to be defined.

## Compliance

- `tests/unit/gateway/test_llm_gateway.py` asserts the request reaches the
  provider unaltered, that retry and timeout policies are applied, that a
  provider's raw exception text never reaches the caller, and that streaming is
  never retried.
- `tests/unit/sdk/test_contracts.py` pins the exact field sets of the common
  request and response models against `architecture.md` §30.
- `tests/unit/dependencies/test_container.py` asserts the gateway resolves,
  satisfies the protocol, and takes its policies from configuration rather than
  from a default baked into the class.
- `mypy --strict` checks `DefaultLLMGateway` against `LLMGateway` at the point
  of registration in the container.
- The SDK README forbids vendor imports in `agent_platform_sdk`;
  `agent_platform.providers` remains the only package permitted to make them.

## References

- `architecture.md` §30 — Provider-Neutral LLM Contract
- `CLAUDE.md` — Provider Neutrality; Never expose Azure SDK classes outside provider implementations
- `docs/engineering-handbook.md` — LLM Integration Standards
- `.claude/project-spec.md` — FR-016 … FR-019
- [ADR-0004](./0004-provider-abstraction-via-protocols.md) — provider contracts as protocols
