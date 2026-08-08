# ADR-0001: Target Python 3.12 and standardise on uv

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 01 — Repository Foundation

## Context

`architecture.md` §80 and the engineering handbook specify "Python 3.12+" and
`uv` for dependency management. Both leave a choice open that has to be made
concretely, because it is written into `pyproject.toml`, both Dockerfiles, CI,
and the developer setup guide:

1. **Which interpreter** do we actually target? The development machine had only
   Python 3.14.6 installed, which satisfies "3.12+" literally.
2. **Are we bounded above?** An unbounded `requires-python` invites `uv` to
   resolve a universal lock across interpreters we have never tested on.

The dependencies that matter here are the ones later milestones commit to:
LangGraph and LangChain (Milestone 03), the Azure AI SDKs (Milestone 05), and
`dependency-injector`, which ships compiled extensions and has historically
lagged new interpreter releases by months.

A dependency without a wheel for the target interpreter does not fail
gracefully. It falls back to a source build, which needs a C toolchain that a CI
runner and a slim container image do not have.

## Decision

Target **Python 3.12**, with `requires-python = ">=3.12,<3.14"`.

- `.python-version` pins 3.12 for `uv`, so every contributor and CI runner
  resolves against the same interpreter.
- Both Dockerfiles take `ARG PYTHON_VERSION=3.12`.
- `mypy` and Ruff are configured for `py312`.
- **uv** is the only dependency manager, using a single workspace lock file
  (`uv.lock`) committed to source control.

## Alternatives Considered

### Target 3.14, matching the machine's interpreter

**Rejected because:** it optimises for one developer's current install against
the platform's stated dependencies. Several packages Milestones 03–05 commit to
have no 3.14 wheels, so the first real provider integration would begin with a
toolchain problem rather than a provider problem.

### Target 3.13

**Rejected because:** it carries most of the 3.14 risk for none of the benefit.
FastAPI and Pydantic support it well, but the LangChain transitive tree and some
Azure AI packages still lag. 3.12 is the newest version where the *entire*
committed stack is uncontroversial.

### Leave `requires-python` unbounded at `>=3.12`

**Rejected because:** `uv` would then resolve a universal lock spanning
interpreters we never test on. That either constrains resolution to the
lowest-common-denominator version of every package, or produces a lock that
installs untested combinations. An upper bound states honestly what we have
verified.

### pip + requirements.txt, or Poetry

**Rejected because:** the handbook already standardises on `uv`, and `uv`
workspaces are what let three packages share one lock file and one virtual
environment without path hacks. Re-litigating a settled decision has no upside.

## Consequences

### Positive

- Every committed dependency has a prebuilt wheel; no container or CI runner
  needs a C toolchain.
- One lock file across backend, SDK and shared packages, so a version can never
  diverge between them.
- `uv sync --frozen` in CI fails when the lock and manifests disagree, catching
  a dependency change committed without its lock update.

### Negative

- We forgo 3.13 and 3.14 performance improvements until we deliberately move.
- The upper bound must be raised deliberately. That is the point, but it is
  still recurring maintenance.
- Contributors on a newer system Python need `uv` to fetch 3.12. `uv` does this
  automatically, so the cost is one download, not a manual install.

### Neutral

- Raising the ceiling is a small, reviewable change: `.python-version`,
  `requires-python`, the two `ARG`s, and the `mypy`/Ruff targets.

## Compliance

- CI runs `uv sync --all-packages --frozen`, which fails on lock drift.
- `mypy` is pinned to `python_version = "3.12"`, so a 3.13-only construct is a
  type error.
- Ruff's `target-version = "py312"` rejects syntax the target cannot parse.

## References

- `architecture.md` §80 — Recommended Technology Versions
- `docs/engineering-handbook.md` — Backend Technology Stack, Dependency Management
- [ADR-0003](./0003-workspace-layout-and-package-boundaries.md) — workspace layout
