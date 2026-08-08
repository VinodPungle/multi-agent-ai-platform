# ADR-0004: Declare provider contracts as `typing.Protocol`

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 01 — Repository Foundation

## Context

The platform's central promise is that a provider is replaceable through
configuration alone: Azure AI Foundry today, Anthropic or Ollama tomorrow, with
no change to business logic. `CLAUDE.md` names the abstractions —
`LLMProvider`, `MemoryProvider`, `SearchProvider`, `EmbeddingProvider`,
`VectorStoreProvider`, `ToolProvider`, `PromptProvider`, `EvaluationProvider` —
and requires each capability to have an interface, an implementation, a factory
and configuration.

How the interface is *declared* determines what an implementer must do to
satisfy it. With an abstract base class, satisfying the contract means importing
and inheriting from a platform type. That is a dependency in the wrong
direction: an adapter around a vendor SDK must know about us in order to be
usable by us.

A second question follows from `architecture.md` §44: routing must be decided by
capability, never by provider identity. That has to be expressible in the
contract, or it becomes a convention.

## Decision

Every provider contract is a `typing.Protocol`, decorated `@runtime_checkable`,
in `agent_platform_sdk.interfaces`.

A base `Provider` protocol carries what the runtime needs from anything:
`provider_id`, `initialize()`, `health_check()`, `supports(capability)`,
`close()`. Each capability protocol extends it.

Three supporting decisions:

**Capability is data, not type.** `supports(capability)` takes a `Capability`
enum member. Routing asks "does this support tool calling?", never "is this the
Azure provider?" — the first keeps working when a provider is added, the second
does not.

**Every method takes an `ExecutionContext`.** Provider calls are attributable in
logs and traces without the provider reaching for ambient state.

**`health_check()` must not raise.** An unreachable dependency is an
`UNHEALTHY` result. One failing provider must not break the endpoint that exists
to report which provider is failing.

## Alternatives Considered

### Abstract base classes

**Rejected because:** inheritance points the dependency the wrong way. Every
provider — including a thin adapter around a vendor SDK, and every test double —
would import a platform base class. It also forecloses adapting a third-party
object that already has the right shape but cannot be made to inherit from ours.

The one thing ABCs give that protocols do not is an error at class-definition
time for a missing method. `mypy --strict` reports the same mistake at the point
of registration, which is early enough.

### Duck typing with no declared interface

**Rejected because:** the contract would exist only in documentation. There would
be nothing for `mypy` to check and nothing for a new provider author to read. The
handbook's "Explicit interfaces" rule exists precisely to prevent this.

### `abc.ABC` plus a registration decorator

**Rejected because:** it adds a registration mechanism to work around a problem
protocols do not have.

### Capability as a marker protocol per feature (`SupportsStreaming`, …)

**Rejected because:** capabilities are configuration-driven and can differ per
*model* within one provider — Azure AI Foundry serves models that support tool
calling and models that do not. A type cannot vary per instance; an enum set
can.

## Consequences

### Positive

- A provider implementation imports no platform base class; it satisfies the
  contract structurally.
- Test doubles are plain classes. `tests/integration/api/test_health_endpoints.py`
  defines a `StubProvider` that satisfies `Provider` without inheriting anything.
- `@runtime_checkable` allows an `isinstance` check at registration, so a
  misconfigured provider is rejected at startup rather than on a user's request.
- Adding a provider requires no change to the runtime, the registries, or any
  existing provider.

### Negative

- `@runtime_checkable` checks method *presence*, not signature. A provider with
  the right method names and wrong parameters passes `isinstance` and fails at
  call time. `mypy --strict` catches this statically; a plugin loaded
  dynamically at runtime would not be covered.
- Protocols cannot supply shared implementation. Common behaviour — retry
  wrapping, telemetry — belongs in a decorator or a mixin the provider composes,
  not in the contract. This is the "composition over inheritance" principle
  applied, but it is more typing than a base class with a concrete method.
- A protocol with many members produces long error messages when unsatisfied.

### Neutral

- `Registry[TItem]` uses PEP 695 generic syntax, available from Python 3.12 —
  consistent with [ADR-0001](./0001-python-version-and-toolchain.md).

## Compliance

- `tests/unit/sdk/test_contracts.py` asserts that a standalone class satisfies
  `Provider` without inheriting, and that an incomplete one does not.
- `mypy --strict` checks every provider against its protocol at the point of
  registration.
- The SDK's README states the rule that no vendor SDK may be imported into
  `agent_platform_sdk`; `agent_platform.providers` is the only package permitted
  to do so.

## References

- `CLAUDE.md` — Always use interfaces; Never write provider-specific logic inside business logic
- `architecture.md` §29 — Provider Interface, §44 — Capability Discovery
- `docs/engineering-handbook.md` — Provider Implementations, Provider Development Checklist
