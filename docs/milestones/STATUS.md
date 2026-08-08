# Milestone status

Only one milestone is active at a time. A milestone is complete only when every
acceptance criterion is verified, not merely implemented.

| # | Milestone | Status | Completed |
| --- | --- | --- | --- |
| 01 | [Repository Foundation](./milestone-01-foundation.md) | ✅ **Complete** | 2026-08-08 |
| 01.5 | [Developer Experience](./milestone-01.5-developer-experience.md) | ✅ **Complete** | 2026-08-08 |
| 02 | [Chat UI, Session Memory](./milestone-02-chat-ui-session-memory.md) | ⬜ Next | — |
| 03 | [Agent Runtime (LangGraph)](./milestone-03-agent-runtime-langgraph.md) | ⬜ Not started | — |
| 04 | [Internet Search, Tool Framework](./milestone-04-internet-search-tool-framework.md) | ⬜ Not started | — |
| 05 | [Azure AI Foundry, Gemma 4](./milestone-05-azure-ai-foundry-gemma4.md) | ⬜ Not started | — |
| 06 | [Infrastructure as Code](./milestone-06-infrastructure-as-code.md) | ⬜ Not started | — |
| 07 | [DevSecOps, CI/CD](./milestone-07-devsecops-cicd-github-actions.md) | ⬜ Not started | — |
| 08 | [Production Hardening](./milestone-08-production-hardening-operational-readiness.md) | ⬜ Not started | — |
| 09 | [Enterprise Expansion](./milestone-09-enterprise-expansion.md) | ⬜ Not started | — |

---

## Milestone 01 — Repository Foundation ✅

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| `docker compose up` starts frontend and backend | ✅ | Both containers started; backend reached `healthy`, frontend served the Vite dev bundle |
| Backend health endpoints respond successfully | ✅ | `/live`, `/ready` and `/health` returned 200 from the running container |
| Frontend renders the application shell | ✅ | Shell, navigation, and both status cards render; 12 component tests |
| CI passes locally | ✅ | Every gate in `ci.yml` run locally — see below |
| Configuration validates at startup | ✅ | 30 configuration tests, including all four production invariants |
| Logging and tracing initialize successfully | ✅ | Verified in-process and in the container; records carry correlation and trace IDs |

### Test cases

| Case | Status | Detail |
| --- | --- | --- |
| Health endpoint returns HTTP 200 | ✅ | Plus 503 from `/ready` when a provider is unhealthy |
| Configuration fails for invalid required values | ✅ | Invalid port, sample ratio, log level, environment; unknown keys; production invariants |
| Frontend renders without console errors | ✅ | `console.error` and `console.warn` spied and asserted not called |
| Docker Compose starts successfully | ✅ | Both services up; backend health check passing; hot reload confirmed on both |

### Verification performed

```
Backend    ruff .............. All checks passed
           black ............. 87 files unchanged
           mypy --strict ..... no issues in 87 source files
           pytest ............ 150 passed, 97% statement coverage

Frontend   eslint ............ no problems
           prettier .......... all files formatted
           tsc (strict) ...... no errors
           vitest ............ 33 passed, 86.7% statement coverage
           vite build ........ 320 kB / 95 kB gzipped

Infra      az bicep build .... main.bicep + 5 modules compile with no diagnostics

Containers backend image ..... built; /live, /ready, /health, /api/v1/info all 200
           frontend image .... built; serves the bundle and /healthz
           non-root .......... backend uid 10001, frontend uid 101
           compose ........... both healthy; CORS preflight correct
           hot reload ........ WatchFiles reload confirmed on a backend edit
```

### Delivered beyond the written scope

- **`docs/adr/`** — five ADRs recording the decisions Milestone 01 forced.
  Required by `CLAUDE.md` but not itemised in the milestone document.
- **`/api/v1/info`** — reports build identity and effective feature flags.
  Answers "what is actually deployed here?" without shelling into a container.
- **Configurable Compose host ports** — `BACKEND_PORT` / `FRONTEND_PORT`. Added
  after a real port collision during verification.

### Defects found during verification, and fixed

Recorded because each was invisible to the test suite as written, and the gap
that hid it was worth closing.

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| `pydantic-settings` JSON-decodes collection fields from environment variables before any validator runs, so `PLATFORM_SERVER__CORS_ORIGINS` raised `SettingsError` at startup | Running the Compose stack. Unit tests missed it because they constructed `ServerSettings` directly rather than binding through the environment. | `NoDecode` annotation; two tests that bind through the environment |
| The dotenv source hands *every* key in `.env` to the model, so `extra="forbid"` rejected the `VITE_*` and port variables that deliberately share the file — the backend refused to start as soon as a developer copied `.env.example` to `.env` | Running the gates after `.env` was created. Never seen in Docker, because `.dockerignore` excludes `.env`. | `_NamespacedDotEnvSource` filters the file to the `PLATFORM_` prefix; four tests write a real `.env` |
| The test suite was not isolated from the repository's own `.env`, so results depended on whether a developer had created one | Exposed by the fix above | The autouse fixture now also runs each test in an empty temporary directory |

The pattern is consistent: every one hid behind a test that exercised a
convenient path rather than the real one. Tests now bind through the
environment and through a file on disk, as production does.

### Known limitations

1. **No provider is registered.** `HealthService` probes an empty tuple, so the
   provider health path is exercised only by test stubs. Correct for this
   milestone — the first real provider arrives in Milestone 05.
2. **Tracing has no exporter by default.** Spans are created and correlate log
   records, but nothing is exported until `PLATFORM_TELEMETRY__OTLP_ENDPOINT` is
   set. An OpenTelemetry Collector is provisioned in Milestone 06.
3. **Bicep templates are unprovisioned.** They compile and CI lints them, but
   `azd up` has never been run. Deliberate: Milestone 01 is explicitly
   "local development first".
4. **`.env.example` and the settings model can drift.** Nothing yet asserts they
   agree. Worth a test.
5. **No end-to-end browser test.** Playwright is in the documented stack but has
   no test to run until there is a user journey (Milestone 02).
6. **CI has never executed on GitHub.** Every step was run locally, but the
   workflow itself is unproven against real runners.
7. **Frontend routing is deferred.** Milestone 01 has one page;
   `react-router-dom` is installed but unused until Milestone 02.

### Deviations from documented standards

| Deviation | Reason |
| --- | --- |
| `MemoryError` → `MemoryOperationError`, `Timeout` → `PlatformTimeoutError` | The handbook's example names shadow Python builtins. `except MemoryError` catching a platform error instead of a real out-of-memory condition would be a genuinely dangerous bug. |
| `requires-python = ">=3.12,<3.14"` rather than open-ended `3.12+` | An unbounded range makes `uv` resolve across interpreters the platform has never been tested on. See [ADR-0001](../adr/0001-python-version-and-toolchain.md). |

---

## Architectural refinement — Provider-Neutral LLM Contract and LLM Gateway

Between Milestone 01 and Milestone 01.5. No milestone scope was changed and no
runtime capability was added.

### What prompted it

`architecture.md` §30 documents a provider-neutral contract and an LLM Gateway
that had no counterpart in code. The gap was cheap to close now and expensive
later: Azure AI Foundry arrives in Milestone 05, and a first provider written
before the gateway exists would define the shape of the call path.

### Audit result

Every location in the repository that could couple to Azure AI Foundry was
reviewed against `CLAUDE.md`, `project-spec.md`, `architecture.md` and the
engineering handbook.

| Location | Finding |
| --- | --- |
| `src/backend`, `src/sdk`, `src/shared` | No Azure SDK is imported anywhere. No Azure request or response type exists. |
| `agent_platform.providers` | Empty. Documented as the only package permitted a vendor import. |
| `TelemetrySettings.azure_monitor_connection_string` | A vendor-named configuration value, not a coupling: it is exported through an OTLP collector and no Azure SDK reads it (ADR-0005). Left as is. |
| Doc comments naming Azure | Illustrative only, in docstrings explaining what an abstraction exists for. |

The refactor was therefore additive. Nothing had to be untangled.

### What changed

- `LLMGateway` and `LLMProviderResolver` contracts in the SDK.
- `DefaultLLMGateway` and `ConfiguredProviderResolver` in the backend, wired in
  the composition root.
- The common request and response models completed to match `architecture.md`
  §30 — `system_prompt`, `top_p`, `response_format`, `metadata`,
  `provider_metadata`, `model_metadata`.
- Gateway policy externalised as `PLATFORM_LLM_GATEWAY__*`.
- [ADR-0006](../adr/0006-llm-gateway-and-provider-neutral-contract.md).

### Verification

```
ruff .............. All checks passed
black ............. 93 files unchanged
mypy --strict ..... no issues in 93 source files
pytest ............ 197 passed (150 before, 187 before the last two test files)
```

The 150 tests that existed before this work all still pass unmodified: no
behaviour was changed, only added.

### Known limitations

1. **The gateway has no caller yet.** The Agent Runtime arrives in Milestone 03.
   Until then the gateway is exercised by tests, not by traffic.
2. **No provider is registered.** `llm_providers` is an empty tuple, so every
   resolution fails with `NotFoundError` by design. Azure AI Foundry registers
   in Milestone 05.
3. **`response_format` is carried but not honoured.** Providers implement it
   from Milestone 05.

---

## Milestone 01.5 — Developer Experience ✅

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Fresh clone can be started with documented steps | ✅ | Bootstrap run end to end; `verify_environment.py` reported the real machine correctly (7 tools, Task absent and correctly optional) |
| Pre-commit hooks execute successfully | ✅ | `pre-commit run --all-files` — 17 hooks pass; `--hook-stage pre-push` — 9 pass |
| VS Code recommends required extensions | ✅ | `.vscode/extensions.json`, with conflicting extensions listed as unwanted |
| Backend launches in debug mode | ✅ | Two configurations, including one without the reloader so startup breakpoints are hit |
| Frontend launches in debug mode | ✅ | Chrome and Edge, with a background task matcher so the browser waits for Vite |
| `task dev` starts the environment | ⚠️ Partial | `Taskfile.yml` defines it as parallel `dev:backend` + `dev:frontend`, and both underlying commands were run directly and work. **Task itself was never executed** — it is not installed on the verification machine, and installing it was not in scope. The YAML is schema-valid; the task semantics are unproven. `.vscode/tasks.json` covers the same ground without Task. |

### Defects found during verification, and fixed

Both were found by running the tooling rather than by reading it, and neither was
visible in the configuration itself.

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| The pinned `ruff-pre-commit` hook (0.8.4) rejected code the project's ruff (0.16.2, from `uv.lock`) accepts — `BLE001` on a deliberately blind `except` in `health_service.py`. The hook would have blocked a commit CI passes. | First `pre-commit run --all-files` | All Python and Node hooks converted to `repo: local`, invoked through `uv run` / `npm`, so `uv.lock` is the only place a version is declared. Recorded in [ADR-0007](../adr/0007-task-runner-and-git-hook-strategy.md). |
| `check-json` failed on `src/frontend/tsconfig*.json` — TypeScript configs are JSONC, and the hook only knew about the `.vscode/` and `.devcontainer/` exclusions | Same run | Exclusion extended to the tsconfig files |
| `mixed-line-ending --fix=lf` would have rewritten `bootstrap.ps1`, which `.gitattributes` checks out as CRLF — the file would have shown as modified forever | Reading the two configs against each other before running the hook | Hook excludes `.ps1/.psm1/.psd1/.bat/.cmd`; `.editorconfig` corrected to match `.gitattributes`, which it had disagreed with for `.ps1` |

The `end-of-file-fixer` hook also added a missing final newline to
`.claude/CLAUDE.md` and removed a stray blank line from `.claude/project-spec.md`
— the first thing the new hooks did was find two files that had been wrong since
Milestone 01.

### Verification performed

```
pre-commit (pre-commit stage) ... 17 hooks passed
pre-commit (pre-push stage) ..... 9 hooks passed
verify_environment.py ........... exit 0 on a real machine, Task correctly optional
ruff ............................ All checks passed
black ........................... 97 files unchanged
mypy --strict ................... no issues in 97 source files
pytest .......................... 236 passed (197 before)
```

### Deviations from the milestone document

| Deviation | Reason |
| --- | --- |
| `scripts/verify_environment.py`, not `verify-environment.py` | A hyphen makes the module non-importable, so it could not be unit-tested. The platform requires every component to be independently testable; the file is invoked by path, so nothing else changes. |
| `scripts/clean.py` added | `Taskfile.yml` needs a cache-cleaning task, and `rm -rf` is not a command on Windows. |

### Known limitations

1. **The Dev Container has never been built.** Its Dockerfile and
   `devcontainer.json` are committed and reviewed, but no container has been
   started from them. The versions it pins (uv 0.5.14, Task 3.40.1, Bicep
   v0.32.4) are unverified against each other.
2. **No `task` command has ever been run.** Task is not installed on the
   verification machine. Every command inside `Taskfile.yml` was executed
   directly and passes; the file is schema-valid YAML; but the runner's own
   behaviour — parallel `deps`, `dir:` handling, task-to-task references — is
   unproven. The first person to install Task should run `task --list` and
   `task check` before trusting it.
3. **`.vscode/launch.json` "attach to container" needs debugpy in the image**,
   which the Compose stack does not start. The configuration is correct; the
   container-side half arrives when someone needs it.
4. **Nothing checks that `.env.example` and the settings model agree** — carried
   over from Milestone 01, and now joined by a second drift risk: the Dev
   Container's tool versions and the ones CI installs.
5. **Hooks require bootstrap to have run.** A clone-then-commit sequence gets a
   "command not found" from the hook rather than a clean skip.

---

## Next: Milestone 02 — Chat UI and Session Memory

Not started. Awaiting approval before any work begins.
