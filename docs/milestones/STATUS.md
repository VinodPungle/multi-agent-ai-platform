# Milestone status

Only one milestone is active at a time. A milestone is complete only when every
acceptance criterion is verified, not merely implemented.

| # | Milestone | Status | Completed |
| --- | --- | --- | --- |
| 01 | [Repository Foundation](./milestone-01-foundation.md) | ✅ **Complete** | 2026-08-08 |
| 01.5 | [Developer Experience](./milestone-01.5-developer-experience.md) | ✅ **Complete** | 2026-08-08 |
| 02 | [Chat UI, Session Memory](./milestone-02-chat-ui-session-memory.md) | ✅ **Complete** | 2026-08-08 |
| 03 | [Agent Runtime (LangGraph)](./milestone-03-agent-runtime-langgraph.md) | ✅ **Complete** | 2026-08-08 |
| 04 | [Internet Search, Tool Framework](./milestone-04-internet-search-tool-framework.md) | ⬜ Next | — |
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

## Milestone 02 — Chat UI and Session Memory ✅

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Chat page loads | ✅ | Route at `/chat`, lazy-loaded; 20 component tests drive the real tree |
| User can submit prompts | ✅ | Send button, Enter to send, Shift+Enter for a newline, IME-safe |
| Responses stream from the mock provider | ✅ | Verified against a running server: `started` → 60+ `delta` → `completed` |
| Session memory maintains the conversation | ✅ | Turn 2 of a live conversation reported "turn 2"; 4 messages stored |
| Markdown renders correctly | ✅ | Headings, lists, tables, blockquotes and links become elements |
| Code blocks are highlighted | ✅ | `rehype-highlight` with tokens keyed to the theme; per-block copy button |
| Dark mode works | ✅ | Three-state preference (system/light/dark), persisted, `data-theme` on `<html>` |
| Mobile layout is usable | ✅ | Fluid widths, `max-w-[min(46rem,85%)]` bubbles, wrapping header, scrollable code |

### Test cases

| Case | Status | Detail |
| --- | --- | --- |
| Multiple sequential prompts | ✅ | Conversation id is reused; history grows; the model sees earlier turns |
| Long streamed responses | ✅ | 60+ chunk stream reassembles exactly; `memo` keeps re-render cost flat |
| Browser refresh clears the session | ✅ | Conversation lives in React state; a new process starts empty (asserted) |
| Empty prompt validation | ✅ | Rejected at the boundary, in the service, and disabled in the UI |
| Network interruption handling | ✅ | Transport failure, mid-stream failure and cancellation are three distinct paths |

### What was built

**Backend.** A `MockLLMProvider` implementing the real `LLMProvider` contract —
not a stub in the service layer, so it routes through the LLM Gateway exactly as
Azure AI Foundry will. `InMemorySessionMemoryProvider`, bounded and LRU-evicting.
`ChatService`, depending only on the `LLMGateway` and `MemoryProvider` protocols.
An SSE encoder, and five chat routes.

**Frontend.** An SSE client built on `fetch` (not `EventSource` — see
[ADR-0008](../adr/0008-server-sent-events-for-streaming-chat.md)), a `useChat`
hook owning the streaming lifecycle, and a chat interface with Markdown, syntax
highlighting, typing indicator, stop, regenerate and clear. Routing arrives with
the second module, as planned.

### Defects found during verification, and fixed

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| Validation ran *inside* the streaming generator, which `StreamingResponse` does not iterate until after the 200 and SSE headers are sent — so an empty message got a 200 and an SSE stream instead of a 422 | Integration test asserting the status code of a whitespace-only streamed message | `ChatService.stream()` became an `async def` returning an iterator, so everything that can fail cheaply fails before the response is committed |
| The `started` event published `provider_id: ""` — the gateway resolves the provider when the first chunk is requested, which is after that event must be sent | Reading the real SSE output from a running server; every test passed | Field removed. A field that is always wrong is worse than an absent one; attribution is on the non-streaming response and in telemetry |
| `request()` threw on a 204, so a successful `DELETE` surfaced as a network failure | Writing the clear-conversation path | 204/205 short-circuit before `response.json()` |
| The production bundle grew to 712 kB because `rehype-highlight` statically imports lowlight's full `common` language set — a `languages` option cannot shrink it | `vite build` size warning | Chat route lazy-loaded: initial bundle 366 kB, chat chunk 346 kB fetched on first visit. An earlier attempt to restrict the language list was removed once measurement showed it saved nothing and only narrowed coverage |
| The mock provider's default `enabled=true` made every production-like configuration invalid | Two pre-existing configuration tests failed | Default flipped to `false`, matching the posture of every other setting in the file; enabled explicitly in `.env.example` and Compose |

### Verification performed

```
Backend    ruff .............. All checks passed
           black ............. 109 files unchanged
           mypy --strict ..... no issues in 109 source files
           pytest ............ 360 passed, 97% statement coverage  (197 before)

Frontend   eslint ............ no problems
           prettier .......... all files formatted
           tsc (strict) ...... no errors
           vitest ............ 70 passed  (33 before)
           vite build ........ 366 kB initial + 346 kB chat chunk

Live       streaming ......... started → 60+ deltas → completed, against a real server
           session memory .... turn 2 saw turn 1; 4 messages stored
           clear ............. DELETE returned 204
```

### Known limitations

1. **Memory is process-local.** `InMemorySessionMemoryProvider` is not shared
   between replicas, so it must not run behind a load balancer. Redis replaces
   it by configuration.
2. **No reconnection.** A connection dropped mid-generation loses the remainder
   of that answer. The partial text is kept and the user can regenerate.
3. **A mid-stream failure returns HTTP 200.** Monitoring that watches status
   codes alone will not see it; the `chat.turn_failed` log event carries it.
4. **The mock provider is not a model.** Its answers are templated and
   deterministic. Anything that appears to work because of *what* it says is
   proving nothing.
5. **No end-to-end browser test.** The component tests run in jsdom, which has
   no layout — so scroll-following and responsive behaviour are verified by
   inspection, not by assertion. Playwright arrives in Milestone 08.
6. **Conversation history is not restored on reload.** The backend keeps it and
   `GET /conversations/{id}` returns it, but the frontend holds the id in React
   state only. Deliberate: "until browser refresh" is the milestone's stated
   scope.

---

## Milestone 03 — Agent Runtime and LangGraph ✅

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Runtime executes ChatAgent | ✅ | Every chat turn now goes service → runtime → engine → agent → gateway; verified against a running server |
| LangGraph orchestrates execution | ✅ | `LangGraphWorkflowEngine` compiles and invokes a state graph; it is the default engine |
| Execution context propagates | ✅ | Agent, model, provider, execution id stamped by the runtime; correlation id survives; caller's context never mutated |
| Registries resolve implementations | ✅ | Agent, provider, model and tool registries; startup refuses an agent naming a model no provider serves |
| Mock provider continues to work | ✅ | All Milestone 02 integration tests pass unchanged against the new path |
| Telemetry captures runtime execution | ✅ | Spans per runtime and workflow call; five runtime event types observed in a live run |

### Test cases

| Case | Status | Detail |
| --- | --- | --- |
| Agent registration | ✅ | Duplicate registration refused; a miss names what is registered |
| Workflow execution | ✅ | One suite parametrised across both engines |
| Runtime failure handling | ✅ | A `ProviderError` survives the graph unchanged rather than becoming a `WorkflowError` |
| Registry lookup | ✅ | 12 tests on the single implementation every registry shares |
| Prompt loading | ✅ | Versioning, pinning, rollback listing, and six malformed-file cases |
| Execution context propagation | ✅ | 5 tests, including that an existing execution id is not replaced |

### What was built

`AgentRuntime` owning the lifecycle; `WorkflowEngine` with two implementations
(LangGraph and a deliberate twenty-line `direct` engine that proves the seam);
`ChatAgent`; agent, provider, model and tool registries over one generic
implementation; a file-backed prompt provider with YAML front matter and
versioning; runtime event publication behind an interface; and startup
validation of the wiring.

`ChatService` lost its memory handling, prompt assembly and gateway call — all
three moved into the runtime. What remains is genuinely chat's own: validating a
message, mapping a conversation onto a turn, and translating runtime output into
SSE events. That reduction is the test of whether the runtime earned its place.

### Defects found during verification, and fixed

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| `_logger.debug(..., agent_id=..., **context.to_log_fields())` passed `agent_id` twice, raising `TypeError` inside the logger on every completed turn | First runtime test run | The context already carries it; the explicit argument was removed in both places it appeared |
| **`prompts/` was never copied into the Docker image.** The application would have started and failed every request with "No prompt registered" — a container that looks healthy and cannot answer | Integration tests, which run in a temp directory and so hit the same missing-path condition | `COPY prompts` added to both image stages, plus a read-only Compose mount so editing a prompt is a reload rather than a rebuild |
| Startup validation refused to boot when *no* provider was registered — which is the default until Milestone 05, and what a correct production deployment looks like today | 29 pre-existing tests failed at once | Validation is skipped, with a warning, when there are no providers to validate against |
| The model registry was populated by a synchronous bridge function with an apologetic name | Writing it | Replaced with the correct design: an empty registry filled during async startup by awaiting each provider's `list_models()` |

### Verification performed

```
ruff .............. All checks passed
black ............. 126 files unchanged
mypy --strict ..... no issues in 126 source files
pytest ............ 440 passed, 97% statement coverage  (360 before)

Live   LangGraph engine ... streaming, session memory and 5 runtime event types
       direct engine ...... identical behaviour with no graph library involved
       misconfiguration ... `PLATFORM_AGENT__MODEL_ID=does-not-exist` refuses to
                            start: "names model 'does-not-exist', which no
                            provider serves (available: mock-echo)"
```

### Known limitations

1. **The graph has one node**, compiled per execution. Both are right at this
   size and wrong at some larger one; neither has been measured.
2. **Streaming bypasses the graph.** LangGraph streams state between nodes, not
   tokens within one. A multi-node workflow will need a real answer to per-node
   streaming that this milestone did not have to give.
3. **Budget enforcement is advisory.** A breach is logged and published; the
   answer is still returned, because the tokens are already spent. Real
   enforcement needs a loop that can be stopped — Milestone 04.
4. **One agent, registered from configuration.** A registry loaded from YAML
   descriptors is what more than one agent will need.
5. **No agent or model discovery endpoints.** `/api/v1/agents` and
   `/api/v1/models` are listed in the API conventions and not yet built; the
   registries that would serve them exist.
6. **`_enforce_pre_execution_budget` is empty.** Every `BudgetPolicy` limit is
   post-hoc for a single-call agent. The seam exists for the tool loop.

---

## Next: Milestone 04 — Internet Search and Tool Framework

Not started. Awaiting approval before any work begins.
