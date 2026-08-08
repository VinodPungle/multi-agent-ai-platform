# ADR-0003: uv workspace with three Python packages

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 01 — Repository Foundation

## Context

`architecture.md` §67 specifies `src/backend`, `src/frontend`, `src/sdk` and
`src/shared`, and §70 says the SDK holds shared contracts with the instruction
"never duplicate interfaces across services". The distinction between `sdk` and
`shared` is not spelled out, and the Python import name is not specified at all.

Two concrete questions had to be answered, both of which are expensive to change
once code depends on them:

1. **What is the import root?** `platform` is unusable — it shadows a standard
   library module. The handbook's naming standard bans abbreviations
   (`Mgr`, `Svc`, `Util`).
2. **How is the boundary enforced?** A layout that only *documents* a dependency
   direction is a layout that will be violated, because nothing stops an import.

## Decision

A **uv workspace** with three Python packages and a virtual root:

| Directory | Distribution | Import name | Contents |
| --- | --- | --- | --- |
| `src/shared` | `agent-platform-shared` | `agent_platform_shared` | Correlation context, identifiers, clock. Standard library only. |
| `src/sdk` | `agent-platform-sdk` | `agent_platform_sdk` | Interfaces, DTOs, events, policies. Pydantic only. |
| `src/backend` | `agent-platform-backend` | `agent_platform` | FastAPI application and runtime. |

The dependency direction is strictly one-way and is expressed in the manifests,
not merely in prose:

```
agent_platform  ->  agent_platform_sdk  ->  agent_platform_shared
```

**Why `sdk` and `shared` are separate.** The SDK is a *contract* surface that
outside consumers compile against and that we version carefully. `shared` holds
implementation mechanics that the SDK itself needs — a `contextvars` wrapper, a
clock protocol. Merging them would drag runtime concerns into the contract layer
and mean every consumer of an interface also inherits our correlation plumbing.

**Why `agent_platform` for the backend.** It is descriptive, has no standard
library collision, and reads correctly at every call site
(`from agent_platform.runtime import ...`).

## Alternatives Considered

### A single package with internal subpackages

**Rejected because:** nothing then prevents `domain` importing `providers`. The
dependency rule would be a convention enforced only by review, and conventions
enforced only by review are the ones that erode first under deadline pressure.
Separate distributions make a violation a resolution failure.

### Merge `shared` into `sdk`

**Rejected because:** the SDK would acquire runtime concerns, and every service
importing a contract would inherit them. Keeping `shared` dependency-free is what
lets a future non-Python-backend service reuse the correlation semantics without
pulling in Pydantic.

### `maap` as the import namespace

**Rejected because:** the handbook explicitly bans abbreviations. `maap.runtime`
means nothing to a new engineer, and the repository is meant to be understandable
within a day.

### `platform_core`

**Rejected because:** it avoids the stdlib collision but reads less clearly than
`agent_platform`, and "core" is the kind of non-name the handbook warns about
alongside `Util` and `Helper`.

### Separate repositories per package

**Rejected because:** it is real overhead — three release processes, three CI
pipelines, cross-repository version coordination — for a team that has not yet
shipped Milestone 02. The workspace keeps the boundary without the ceremony, and
extracting a package later is mechanical.

## Consequences

### Positive

- A layering violation fails at dependency resolution, not at review.
- One `uv.lock` covers all three packages, so versions cannot diverge.
- `agent_platform_sdk` can be published for external consumers without shipping
  the backend.
- Each package can be tested in isolation, since neither `sdk` nor `shared`
  imports a web framework.
- Ruff's `ban-relative-imports = "all"` makes every import state its package,
  keeping the direction visible at every call site.

### Negative

- Three `pyproject.toml` files instead of one.
- Adding a dependency requires deciding which package owns it — a small tax that
  is also the mechanism doing the work.
- `src/backend/agent_platform` is one level deeper than `src/agent_platform`.

### Neutral

- The Docker build copies manifests before source so dependency resolution is
  cached separately from source changes.
- Both the backend and frontend live under `src/`, so `src` is not a Python
  source root; the packages sit one level down.

## Compliance

- Manifests declare the direction; `uv sync` enforces it.
- `ban-relative-imports = "all"` in Ruff.
- `known-first-party` in the isort configuration groups the three packages, so a
  cross-package import is visually obvious in a diff.
- `mypy --strict` runs across all three packages together.

## References

- `architecture.md` §67 — Repository Architecture, §68 — Backend Package Structure, §70 — SDK Structure
- `docs/engineering-handbook.md` — Naming Standards, Code Organization
- [ADR-0004](./0004-provider-abstraction-via-protocols.md) — how the contracts are declared
