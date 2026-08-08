# ADR-0011: The Azure AI Foundry provider, and keyless authentication

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 05 — Azure AI Foundry Integration

## Context

Four milestones built a platform whose business logic had never spoken to a real
model. Every chat turn so far was answered by `MockLLMProvider`. This milestone
connects the first real one and, in doing so, tests the claim ADR-0004 and
ADR-0006 have been making since the beginning: that a provider can be added
without touching an agent, the runtime, the gateway or any workflow.

That claim is either true or it is not, and the only way to find out is to add
one.

## Decision

### The provider implements the existing protocol and nothing else

`AzureFoundryProvider` satisfies the `LLMProvider` protocol structurally — no
base class, no registration hook, no changes to the protocol to accommodate
Azure. It joins the tuple the container builds, and the model registry picks up
its `list_models()` entry.

The measured result: **no file outside `providers/azure_foundry/`,
`security/credentials.py`, settings and the container changed.** Agents, runtime,
gateway, workflows, tool loop, memory and API are untouched. The abstraction was
not decorative.

### `azure.*` imports exist in exactly two modules

`CLAUDE.md` forbids Azure SDK types outside provider implementations, so the
provider translates at its own boundary in both directions: `CompletionRequest`
→ `UserMessage`/`SystemMessage`/`ChatCompletionsToolDefinition` on the way in,
`ChatCompletions` → `CompletionResponse` on the way out, `HttpResponseError` →
`ProviderError` on failure. `security/credentials.py` is the only other module
importing `azure`, and it exists so the credential is built in one place rather
than wherever someone needs one.

Enforcement is a grep away and belongs in CI eventually; today it is a review
checklist item and a test asserting the provider satisfies the protocol.

### `DefaultAzureCredential`, and no key setting at all

There is no `api_key` field in `AzureFoundrySettings`. Not "unset by default" —
absent, so there is nothing to populate, commit or leak. `az login` locally and
Managed Identity in Azure resolve through the same credential chain, which means
**the code path is identical in development and production**: the class of bug
where auth works locally and fails in the cloud does not exist here.

The chain is deliberately not narrowed. Narrowing it optimises credential
resolution by a few milliseconds once per process and breaks every environment
whose mechanism was excluded — a bad trade.

### Neither `initialize()` nor `health_check()` calls the model

Managed Compute with scale-to-zero bills for an instance the moment one starts.
A readiness probe that made an inference call would wake the deployment on every
poll, and a container that inferred at startup would wake it on every rolling
restart. Both turn a cost-saving feature into a cost — quietly, on a schedule,
with no request to attribute it to.

So `initialize()` validates the endpoint is an HTTPS URL and constructs the
client; `health_check()` reports configuration validity. Connectivity is proven
by the first real request.

This is an honest trade, not a free win: the platform can report healthy while
the deployment is unreachable. That is the correct default for scale-to-zero, and
an operator who needs stronger readiness should add an explicit warm-up endpoint
rather than make the probe pay per poll.

### Cost comes from configuration, and defaults to zero

The inference API does not report spend. Rates are configured per deployment and
default to `Decimal(0)`, so an unconfigured deployment reports **zero cost rather
than a plausible-looking estimate**. A wrong number that reaches a cost dashboard
is worse than a missing one: nobody investigates a figure that looks right.

`count_tokens()` is a documented character-based estimate for the same reason —
the service returns real usage on every response, and the estimate exists only
for pre-flight budget checks. It is labelled as an estimate everywhere it is
returned.

### The output-token parameter is configuration

Reasoning models reject `max_tokens` with an HTTP 400 and require
`max_completion_tokens`. `output_token_parameter` selects between them, sending
the non-default through the SDK's `model_extras` pass-through.

This was **found by a live call, and could not have been found any other way**.
Every unit test passed. Every fake accepted `max_tokens` without complaint,
because a fake accepts whatever it is handed. The parameter is not ignored by the
service — it is rejected — and no amount of mocking reproduces a service's
opinion about its own API.

### Streaming is not retried

Inherited from ADR-0006 and worth restating at the provider: once a chunk has
reached the client, a retry would duplicate the answer. The provider closes the
SDK stream in a `finally` so an abandoned generator does not leak a connection.

## Consequences

**Good.** The provider abstraction is proven rather than asserted. Adding
Anthropic, OpenAI or Ollama is now a known quantity: one package, one settings
block, one container branch. Credentials never touch the repository, an image or
a config file. Cold starts are budgeted rather than surprising.

**Bad.** Health does not prove reachability. Cost is only as accurate as the
configured rates. `count_tokens()` is an estimate. Tool calling is claimed by
configuration, so a misconfigured `supports_tools` routes tool work to a model
that ignores it.

**Unresolved.** **Gemma 4 could not be provisioned on this subscription.** The
`azureml-google` registry returns `User/tenant/subscription is not allowed to
access registry azureml-google`; the Foundry account's catalogue lists 135
models, none from Google. This is a tenant entitlement matter, not an
architectural one — the provider names no model anywhere in its source, so
serving Gemma 4 is a two-line environment change once the entitlement exists.
Live verification therefore used the subscription's existing deployment.

## Alternatives considered

**API key authentication.** Simpler to configure and explicitly discouraged by
`CLAUDE.md`. It also creates a secret to store, rotate and eventually leak, and
diverges local from production auth.

**Health check that calls the model.** Genuinely proves reachability. Rejected
because it defeats scale-to-zero, which is the reason Managed Compute was chosen.

**A generic OpenAI-compatible provider instead.** Foundry exposes an
OpenAI-shaped surface, so this would appear to work. It gives up
`DefaultAzureCredential`, Azure's error taxonomy and Foundry-specific parameter
handling — and the first milestone's whole point is that Azure is a first-class
target, not a lowest-common-denominator one.

**Waiting for Gemma 4 entitlement before shipping.** Would have left the platform
with no real provider and no evidence the abstraction holds, blocked on a support
ticket outside the repository's control.
