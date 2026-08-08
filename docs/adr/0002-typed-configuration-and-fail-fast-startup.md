# ADR-0002: Strongly typed configuration validated at startup

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 01 — Repository Foundation

## Context

`CLAUDE.md` states three rules that together determine how configuration works:
nothing may be hardcoded; configuration must be validated during startup; and
there must be no scattered environment-variable lookups.

The failure this prevents is specific. A platform that reads `os.environ`
wherever it needs a value fails at the moment a code path first runs — which for
a rarely used branch can be weeks after deployment. Worse, some misconfigurations
never fail at all: `debug=true` in production silently exposes API docs and
internal error detail, and a wildcard CORS origin silently permits every site to
call the API with credentials.

Neither is caught by types. Both are caught by asking, at startup, whether this
configuration is legitimate *for the environment it claims to be*.

## Decision

A single `PlatformSettings` model, built from `pydantic-settings`, loaded once
and validated once at application startup.

**Structure.** Nested section models — `app`, `server`, `logging`, `telemetry`,
`features` — bound from `PLATFORM_<SECTION>__<FIELD>` environment variables.

**Immutable.** Every model is `frozen=True`. Configuration cannot change after
startup.

**Closed.** `extra="forbid"` on every model. A misspelled variable is a startup
failure, not a silently ineffective setting.

**Environment-aware invariants.** A `model_validator` rejects configurations
that are unsafe for a production-like environment (staging or production):

| Rejected | Why |
| --- | --- |
| `app.debug = true` | Exposes API docs and internal error detail |
| `logging.renderer = "console"` | Not machine-parsable; breaks log analytics |
| `"*"` in `server.cors_origins` | Permits any origin to call the API with credentials |
| empty `server.cors_origins` | Almost certainly an unset variable, not a decision |

All violations are reported together, so a fix takes one cycle rather than four.

**Injected, never imported.** `get_settings()` is memoised and called once in
the application factory; every consumer receives the instance through the
dependency-injection container. No module reads the environment directly.

**Namespace-filtered `.env`.** One `.env` at the repository root serves the
backend, the frontend and Docker Compose, so it legitimately contains `VITE_*`,
`BACKEND_PORT` and `FRONTEND_PORT` alongside `PLATFORM_*`. Unlike the
process-environment source, `pydantic-settings`' dotenv source hands *every* key
in the file to the model, which `extra="forbid"` then rejects. A custom
`_NamespacedDotEnvSource` filters the file to the `PLATFORM_` prefix.

Filtering rather than relaxing `extra` is the point: a misspelled `PLATFORM_*`
variable remains a startup failure, while a variable belonging to another tool
is correctly ignored.

## Alternatives Considered

### Read `os.environ` at each point of use

**Rejected because:** it is the exact failure mode the rules exist to prevent.
Failures surface at request time, in whichever code path happens to run first,
and there is no single place to see what the platform is configured to do.

### Validate types only, without environment invariants

**Rejected because:** every value in the table above is *type-valid*.
`debug=true` is a perfectly good boolean. Type checking cannot express "this
value is legitimate in development and dangerous in production" — that requires
a cross-field validator that knows the environment.

### Fail lazily — log a warning and continue

**Rejected because:** a warning during startup is read by nobody. Booting a
misconfigured instance means serving traffic under configuration nobody chose,
which is worse than an outage that names its cause. This is what "Fail Fast"
means in practice.

### Flat variable names such as `PLATFORM_SERVER_PORT`

**Rejected because:** with a single underscore, `PLATFORM_APP_NAME` is ambiguous
between `app.name` and a section called `app_name`. The `__` delimiter is
unambiguous and is what `pydantic-settings` supports natively.

## Consequences

### Positive

- A misconfigured instance cannot start. The four highest-consequence
  misconfigurations are impossible to deploy.
- Every setting is discoverable in one file and documented in `.env.example`.
- Tests construct settings directly, so an application under test needs no
  environment manipulation.
- The frontend mirrors the pattern in `config/env.ts`, validating with Zod at
  module load.

### Negative

- `PLATFORM_SERVER__PORT` is more verbose than `PORT`. The trade is deliberate:
  unambiguous beats short for a value read by operators under pressure.
- Adding a setting means editing the model *and* `.env.example`. CI does not
  currently enforce that they agree.
- `extra="forbid"` means a stale variable left in a deployment blocks startup.
  That is intended — it surfaces configuration drift — but it will surprise
  someone at least once.

### Neutral

- `get_settings` is memoised, so tests that need different values must call
  `get_settings.cache_clear()`. The test suite does this in an autouse fixture.

## Compliance

- `tests/unit/configuration/test_settings.py` asserts each invariant, including
  that all violations are reported together.
- `TestSharedDotEnvFile` writes a real `.env` on disk and asserts that foreign
  keys are ignored while a misspelled `PLATFORM_*` key still fails.
- An autouse fixture strips `PLATFORM_*` from the environment **and** runs each
  test in an empty temporary directory. Both are required: clearing the
  environment alone left the suite reading the repository's own `.env`, which is
  how the dotenv-filtering bug reached a commit.
- Ruff's `PTH` and `T20` rules and the handbook's review checklist cover direct
  environment and `print()` access in review.

## References

- `CLAUDE.md` — Non-Negotiable Rules, Configuration, Fail Fast
- `architecture.md` §71 — Configuration Hierarchy
- `docs/engineering-handbook.md` — Configuration
