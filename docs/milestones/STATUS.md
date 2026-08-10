# Milestone status

Only one milestone is active at a time. A milestone is complete only when every
acceptance criterion is verified, not merely implemented.

| # | Milestone | Status | Completed |
| --- | --- | --- | --- |
| 01 | [Repository Foundation](./milestone-01-foundation.md) | ✅ **Complete** | 2026-08-08 |
| 01.5 | [Developer Experience](./milestone-01.5-developer-experience.md) | ✅ **Complete** | 2026-08-08 |
| 02 | [Chat UI, Session Memory](./milestone-02-chat-ui-session-memory.md) | ✅ **Complete** | 2026-08-08 |
| 03 | [Agent Runtime (LangGraph)](./milestone-03-agent-runtime-langgraph.md) | ✅ **Complete** | 2026-08-08 |
| 04 | [Internet Search, Tool Framework](./milestone-04-internet-search-tool-framework.md) | ✅ **Complete** | 2026-08-08 |
| 05 | [Azure AI Foundry, FW-Kimi-K3](./milestone-05-azure-ai-foundry-gemma4.md) | ✅ **Complete** | 2026-08-08 |
| 06 | [Infrastructure as Code](./milestone-06-infrastructure-as-code.md) | ⚠️ **Complete, not provisioned** | 2026-08-08 |
| 07 | [DevSecOps, CI/CD](./milestone-07-devsecops-cicd-github-actions.md) | ⚠️ **CI green, CD unrun** | 2026-08-08 |
| 08 | [Production Hardening](./milestone-08-production-hardening-operational-readiness.md) | ⚠️ **Complete, undrilled** | 2026-08-09 |
| 09 | [Enterprise Expansion](./milestone-09-enterprise-expansion.md) | ⚠️ **Partial — scope declared** | 2026-08-09 |

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

## Milestone 04 — Internet Search and Tool Framework ✅

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Runtime discovers tools through the registry | ✅ | `tools=['internet-search']` at startup; an agent's declared tool is resolved through `ToolExecutor` |
| Internet Search Tool executes successfully | ✅ | Live run returned real Wikipedia citations for "the eiffel tower" |
| Tool results use platform DTOs | ✅ | `ToolResult` throughout; only title/url/snippet reach the model |
| Runtime handles timeout and retry | ✅ | Per-descriptor timeout and retry policy in the executor; 18 tests |
| Telemetry records tool execution | ✅ | `tool.started` / `tool.completed` events and a span per call |
| Feature flag can disable search | ✅ | With `PLATFORM_FEATURES__SEARCH=false` the tool is not registered, the agent answers without it, and the turn costs one model call |

### Test cases

| Case | Status | Detail |
| --- | --- | --- |
| Tool registration | ✅ | Registry conflict, unknown id, withdrawn tool |
| Successful search | ✅ | Mock and live DuckDuckGo, plus the loop end to end |
| Timeout handling | ✅ | A hanging tool returns a failed result rather than raising |
| Retry behaviour | ✅ | Transient retried, deterministic not, contract violation not |
| Registry resolution | ✅ | Declared-but-unregistered tools are skipped, not fatal |
| Disabled feature flag | ✅ | Verified live |
| Invalid provider configuration | ✅ | Searching before initialisation is refused |

### What was built

A `ToolExecutor` that resolves, authorises, validates, times out, retries and
records — and never raises. The internet-search tool over a `SearchProvider`
abstraction with two implementations: a deterministic offline mock and a real,
**keyless** DuckDuckGo provider, so search works on a fresh clone with no signup.
A tool loop in the workflow layer, shared by both engines. And a mock model that
genuinely requests tools, so the whole path is exercisable deterministically.

Budget enforcement stopped being advisory. Milestone 03 could only report a
breach after the fact; the loop checks `max_tool_invocations` and
`max_model_calls` *between* iterations, where stopping still saves the next call.

### Defects found during verification, and fixed

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| The mock's query stripping removed only the trigger word, turning "search for the eiffel tower" into "for the eiffel tower" — which matches nothing. Every live search silently returned no results. | Running the real API end to end. Every unit test passed, because the mock search backend returns results for any string. | Strip trigger *phrases* (`search for`, `find out about`) rather than words |
| `response.elapsed` is only populated after a response is read, so latency access raised inside the provider | The parsing tests, against `MockTransport` | Measure with `perf_counter` — which also times the budget the provider is accountable for rather than httpx's transport |
| A test asserted `BudgetPolicy(max_tool_invocations=0)`, which the model rejects (`gt=0`) | Writing it | The budget paths moved to focused tests driven by an agent that never stops asking for tools — the right level, since the well-behaved mock cannot reach them |
| A fake clock's `now()` raised, on the assumption the executor only used `monotonic()`; it uses both | Tool executor tests | Fake returns a real timestamp |

The first is the one worth remembering: a mock that is too forgiving hides a
defect in the code that talks to the real thing.

### Verification performed

```
ruff / black / mypy --strict ... clean (134 files)
pytest ....................... 503 passed, 96% coverage   (440 before)
                               78 of them network-free duplicates via `-m "not integration"`

Live   real search ........... "search for the eiffel tower" returned three
                               cited Wikipedia results through the full pipeline
       feature flag off ...... tool not registered; answered without search
```

### Known limitations

1. ~~**Streaming does not use tools.**~~ **Resolved after Milestone 05** — and
   the stated reason was wrong. `CompletionChunk` already had a `tool_calls`
   field; no provider populated it. See the Milestone 05 follow-up below.
2. **The LangGraph graph still has one node**, with the loop inside it rather
   than as `agent → tools → agent` edges.
3. **Tool arguments are hand-validated**, so the declared JSON Schema and the
   check can drift. The trade reverses at the first genuinely complex schema.
4. **DuckDuckGo answers encyclopaedic questions well and current-events
   questions poorly.** It is an Instant Answer API, not a web-results API.
5. **No caching.** Every search is a live call, and repeated identical searches
   in one conversation are repeated cost.
6. **The tool exchange is not visible to the user.** The UI shows the final
   answer with citations but not that a search happened.

---

## Milestone 05 — Azure AI Foundry, FW-Kimi-K3 ✅

**Model:** `FW-Kimi-K3` (Fireworks, `DataZoneStandard` — serverless), deployed on
`multi-agent-ai-platform-resource`. Gemma 4 was the milestone's original model
and could not be provisioned; the substitution is recorded below.

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Azure AI Foundry provider implements `LLMProvider` | ✅ | `isinstance(provider, LLMProvider)`; 47 tests over a fake client |
| Authentication uses `DefaultAzureCredential` | ✅ | Live call succeeded with no API key; there is no key setting to populate |
| A real model answers a real chat turn | ✅ | `POST /api/v1/chat/messages` → HTTP 200, a correct answer, 5.8 s |
| Streaming works through the provider | ✅ | Unit tests over a fake stream; the SDK stream is closed in `finally` |
| Usage and cost are reported | ✅ | `prompt_tokens 320 / completion_tokens 179`, latency and cost filled by the gateway |
| Model metadata comes from the registry | ✅ | `list_models()` built from configuration; nothing in source names a model |
| Health check does not wake a scaled-to-zero deployment | ✅ | Test asserts `client.calls == []` after `health_check()` |
| Existing behaviour unchanged | ✅ | 557 tests pass; no file outside the provider package, credentials, settings and the container changed |

### Model substitution: Gemma 4 → FW-Kimi-K3

Gemma 4 could not be provisioned: `azureml-google` returns `User/tenant/
subscription is not allowed to access registry azureml-google`, and the original
Foundry account's catalogue listed 135 models, none from Google. A tenant
entitlement matter, not an architectural one.

`FW-Kimi-K3` was deployed instead. **Switching models cost no code change** —
three environment variables (`ENDPOINT`, `DEPLOYMENT`, `MODEL_ID`) — which is the
strongest available evidence that the provider abstraction does what it claims.
Two different models on two different subscriptions have now run through it
unmodified.

Note the deployment is **serverless (`DataZoneStandard`), not Managed Compute**,
so the scale-to-zero cold start the milestone anticipated does not apply here.
The cold-start budget remains, correctly, for deployments that do have one.

### An API key was offered and deliberately not used

The deployment's key was supplied. It is not wired in anywhere: `CLAUDE.md`
forbids keys for Foundry where an identity mechanism exists, `AzureFoundrySettings`
has no field to hold one, and `DefaultAzureCredential` already works. The key was
reported as compromised on disclosure and should be rotated.

### What was built

`AzureFoundryProvider` — the first real provider — over `azure-ai-inference`,
translating in both directions at its own boundary so no Azure type escapes.
`security/credentials.py` builds the credential in one place. `azure.*` is
imported by **those two modules and nothing else**, which is the rule `CLAUDE.md`
sets and this milestone was the first opportunity to break.

The result that matters: **adding a real provider changed no agent, no runtime,
no gateway, no workflow and no business logic.** One new package, one settings
block, one branch in the composition root. The abstraction ADR-0004 and ADR-0006
asserted was not decorative.

Neither `initialize()` nor `health_check()` calls the model, deliberately —
either would wake a scale-to-zero deployment on every restart or readiness poll
and bill for it. The cost is that health cannot prove reachability; that trade is
argued in [ADR-0011](../adr/0011-azure-ai-foundry-provider.md).

### Defects found during verification, and fixed

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| **`gpt-5` rejects `max_tokens` with HTTP 400.** Reasoning models require `max_completion_tokens`. | **The live call — and only the live call.** All 35 unit tests passed. Every fake accepted `max_tokens` without complaint, because a fake accepts whatever it is handed. The service does not ignore the parameter; it rejects it. | `output_token_parameter` setting, sending the non-default through the SDK's `model_extras` pass-through; 4 tests added |
| Azure's async credential raised `ImportError: aiohttp not installed` | First live attempt | `aiohttp>=3.11.0` added, documented as azure-core's required async transport |
| `FakeCredential` did not implement `AsyncTokenCredential` in full | `mypy --strict` | The fake now satisfies the whole protocol, including the `get_token` the provider never calls — a double narrower than the contract lets the declared dependency drift from the real one |
| **An Azure SDK enum reached the public API.** `finish_reason` was `str(choice.finish_reason)`, and `str()` on the SDK enum yields the member repr — so `"CompletionsFinishReason.STOPPED"` was returned in the HTTP response body. | The first end-to-end turn against FW-Kimi-K3. Nothing else could have: the mock returns plain strings, so all 43 tests and every local run looked correct. | Read `.value`, which is already the OpenAI-shaped vocabulary (`stop`, `length`, `content_filter`, `tool_calls`). 5 tests added that use the **real SDK enum** rather than a convenient string |
| `AzureFoundrySettings.model_id` defaulted to `"gemma-4"` — a hardcoded model name in source, which `CLAUDE.md` forbids | Visible only once a second model existed | No default; required when the provider is enabled. A stale default silently mislabels every telemetry record and cost row |

Two of these are the same lesson, and it is Milestone 04's: **mocks agree with
you.** The `finish_reason` leak is the sharper example — it was a violation of
the single rule this milestone existed to uphold, sitting in the public API
response, invisible to a test suite that passed 100%. Neither could have been
caught by any amount of unit testing, only by asking the service.

### Live verification

**Six live calls in total across two deployments.** The count matters because a
budget was set, so it is recorded rather than folded into a success summary.

*Against `gpt-5` (first attempt, four calls, ~60 tokens) — one was authorised:*

| # | Outcome |
| --- | --- |
| 1 | HTTP 400 — the `max_tokens` defect above |
| 2 | Diagnostic, confirming `max_completion_tokens` is accepted |
| 3 | **Wasted.** A patch script ran under Windows Python and could not resolve its `/tmp` path, so it failed silently and the call re-used the unfixed parameter |
| 4 | Final confirmation |

Call 3 was avoidable and was my error. The overrun is small in cost and still
worth stating.

*Against `FW-Kimi-K3` (two calls):*

| # | Purpose | Outcome |
| --- | --- | --- |
| 1 | Provider-level round trip | Succeeded first attempt. `max_tokens` accepted, so no parameter override needed |
| 2 | Full stack, `POST /api/v1/chat/messages` | HTTP 200 — and it exposed the `finish_reason` leak, which the provider-level call had not |

The wiring itself — settings, container, registry, agent-to-provider resolution —
was proven **without** a model call, by constructing the container from `.env`
and asserting the agent's provider is registered. Free, and it catches every
configuration error before one token is billed.

The end-to-end result:

```
HTTP 200                    latency 5,797 ms
model_id  fw-kimi-k3        provider_id  azure-foundry
tokens    prompt 320, completion 179      finish_reason  stop

"A vector database is a database optimized to store high-dimensional vector
 embeddings and quickly find the most similar ones, powering features like
 semantic search and retrieval-augmented generation."
```

Two details worth knowing about this model: it consumes reasoning tokens that
are billed but not returned (179 completion tokens for a 200-character answer),
and a small output cap truncates *inside* that reasoning, returning visible
chain-of-thought instead of an answer. Budget accordingly — `max_output_tokens`
below roughly 200 will produce unusable output rather than a short one.

### Verification performed

```
ruff / black / mypy --strict ... clean (139 files)
pytest ....................... 549 passed, 95% coverage   (503 before)
Live   authentication ........ DefaultAzureCredential, no API key
       round trip ............ real usage returned through the platform DTO
```

### Known limitations

1. **Cost rates are not configured**, so every cost figure is currently zero.
   Set `INPUT_/OUTPUT_COST_PER_MILLION_TOKENS` from the deployment's published
   rates before any cost dashboard is believed.
2. **Health does not prove reachability.** A deliberate scale-to-zero trade. An
   operator needing stronger readiness should add an explicit warm-up endpoint
   rather than make the probe pay per poll.
3. **Cost is only as accurate as the configured rates.** The inference API does
   not report spend. Rates default to zero, so an unconfigured deployment reports
   zero rather than a plausible-looking fabrication.
4. **`count_tokens()` is a character-based estimate**, used for pre-flight budget
   checks only; real usage comes back on every response.
5. **`supports_tools` is a configuration claim.** Setting it for a model that
   ignores tool definitions routes tool work into silence.
6. ~~**Streaming still does not use tools**~~ — fixed in the follow-up below.
7. **No automated enforcement that Azure types stay contained.** The
   `finish_reason` leak proves a review checklist is not enough: the violation
   passed review, passed 43 tests and reached the public API. This needs a CI
   check on imports *and* a contract test asserting no response field carries an
   SDK type name.
8. **`FW-Kimi-K3`'s tool calling is unverified.** `supports_tools` is claimed by
   configuration and no live tool call has been made against this model.

---

## Milestone 05 follow-up — making search work in the chat UI ✅

Raised after live testing: the platform had internet search and the UI could not
reach it, and conversation memory looked unreliable.

### Memory was working

Verified through the real API and runtime, with the mock provider so it cost
nothing: two turns in one conversation, four messages stored, history growing.
`_load_history` and `_record` sit in the runtime, above the provider, so this is
provider-independent.

The appearance of forgetfulness came from `uvicorn --reload`: session memory is
in-process, so every file save during development wipes it. The UI already says
so — "lost when the backend restarts".

### Search was genuinely broken, in four separate places

Each was invisible to the suite, and each hid the next.

| # | Defect | Why no test caught it |
| --- | --- | --- |
| 1 | Both engines' `stream()` returned the agent's iterator directly, never running the tool loop. The streaming endpoint — the only one the browser uses — could not call a tool. | Tool tests exercised `execute`. Streaming tests exercised streaming. Nothing asserted the two capabilities composed. |
| 2 | No provider populated `CompletionChunk.tool_calls`. The recorded limitation said the *contract* could not carry a tool call; the field had existed since Milestone 04. | The mock never streamed a tool call either, so the whole streaming-plus-tools path had no coverage on either side. |
| 3 | `CompletionRequest` carried tool **ids** but no schemas, so the provider declared `{"type": "object", "properties": {}}` — a tool taking no arguments. The model was told a tool existed but not how to call it, and some deployments reject an empty schema with HTTP 400. | The mock matches on ids and never reads a schema. It answered correctly no matter what was declared. |
| 4 | `_to_azure_messages` dropped `tool_calls` when converting an assistant message, so the tool result was sent answering a call the transcript never contained. HTTP 400 — **after** the tool had run and been paid for. | No test round-tripped an assistant message carrying tool calls back into a request. |

### Also found, and worse than the four above

**Streamed connections were never closed.** The provider looked for a `close`
method; the SDK's `AsyncStreamingChatCompletions` defines only `aclose`. Every
streamed request leaked its connection until the garbage collector reached it.

The test asserting closure passed throughout, because the fake defined
`close()` — shaped to the code rather than to the SDK. The fake now exposes
`aclose` and only `aclose`.

This is the sharpest example so far of the recurring lesson: **a double that is
more convenient than the real thing tests the double.**

### What was built

`stream_tool_loop`, the streaming counterpart of `run_tool_loop`, shared by both
engines. It streams, collects any tool calls, holds the terminal chunk back
until it knows whether the turn is really over, runs the tools, and streams the
answer — so the consumer sees one uninterrupted answer and never learns there
were two model calls. Usage accumulates across them, because reporting only the
last would under-report what a tool turn cost.

`CompletionRequest.tools` now carries full declarations, resolved by the
workflow layer from the registry. The provider is handed finished declarations
and still never sees a registry, so inference stays uncoupled from tooling.

### Verification

```
ruff / black / mypy --strict ... clean (140 files)
pytest ....................... 592 passed   (566 before)
                               26 new: streaming tool loop across both engines,
                               streamed tool-call assembly, fragment continuation

Live   streaming + search .... tool.completed succeeded=True, 109 ms
                               HTTP 200, 270 delta chunks, grounded answer
Free   multi-turn memory ..... 4 messages stored across 2 turns
```

### Known limitations

1. **Cost still reports zero** until the deployment's rates are configured.
2. **A tool turn's first stream produces no visible text**, so time-to-first-token
   for a searching answer is one full model call plus the tool. Expected, but it
   is the slowest path in the product.
3. **The tool exchange is still invisible to the user.** The UI shows the grounded
   answer with no indication that a search happened.

---

## Follow-up — Tavily search provider ✅

Added on request, so answers can reflect the live web.

**What was there:** `duckduckgo` (keyless, default) and `mock` (offline). The
Instant Answer API returns abstracts, not ranked pages — strong on "what is the
Eiffel Tower", weak on anything current.

**What was added:** `TavilySearchProvider` — ranked web results with extracted
content, built for retrieval augmentation.

It reaches every agent at once, because agents declare the *tool*, not a
backend. Adding it changed **no agent, no tool, no runtime code**: one module,
one member on a literal, one factory branch. That is the third demonstration of
the provider abstraction, after Azure AI Foundry and FW-Kimi-K3.

DuckDuckGo stays the default. A fresh clone with no accounts must still perform
a real search.

### The key is treated as a real secret

Tavily offers no identity-based authentication, so a key is the only mechanism
available — the same narrow exception `CLAUDE.md` allows. It is a `SecretStr`,
sent in an `Authorization` header rather than a query string or body, and
excluded from every error message because an upstream body can echo request
headers back. Three tests assert it does not leak: not into the URL, not into
the body, not into startup logs.

Selecting `tavily` without a key stops startup naming the missing field, rather
than failing the first search with an upstream 401.

### Deliberate choices

- **`raw_content` is discarded.** Tavily returns up to tens of kilobytes per
  result, and every character would be spent context in the next prompt — a
  quiet way to multiply the cost of one search.
- **`health_check` does not search.** Every call is billed, so a probe would
  turn monitoring into spend at whatever rate the orchestrator polls.
- **`search_depth` is configuration.** `advanced` is better and costs more.

### Verification

```
ruff / black / mypy --strict ... clean (142 files)
pytest ....................... 622 passed   (592 before)
                               30 new, over httpx.MockTransport — no key,
                               no account, no billed call in CI
```

Also fixed in passing: a duplicated `perf_counter()` call in the DuckDuckGo
provider that started the timer twice.

### Known limitations

1. **No live verification.** The suite covers request shaping, parsing, error
   mapping and secret handling against a mocked transport, but no real Tavily
   call has been made — there is no account. The first real search is the first
   proof, exactly as with a scale-to-zero deployment.
2. **No caching.** Repeated identical searches in one conversation are repeated
   cost. It matters more now that searches are billed.

---

## Follow-up — the chat UI answers as an agent ✅

Raised on testing: chat should visibly be an *agent* that searches or recalls
when it needs to, not a model answering directly.

Two things were missing, and only one of them was code.

### The agent was never told it could search

The system prompt described tone and Markdown and said nothing about tools. The
tool was declared in the API payload, so the model would use it when explicitly
asked — "search the internet and tell me…" — and otherwise answer from training,
which is what looked like a plain LLM.

Prompt v1.1 says when to search (anything dated, named, or asked for), when not
to (definitions, arithmetic, code, the conversation so far), and to **cite
sources inline** as Markdown links next to the claim they support. It also
states that the conversation so far is provided, so the agent stops asking for
what it has already been told.

A prompt is a versioned asset, so this was a file and a version bump — no code
change, which is the point of `CLAUDE.md`'s rule against prompts in Python.

### The user could not see any of it

A searching turn spends a whole model call plus the search before the first
character appears. The browser showed a blank bubble, indistinguishable from a
hang — and afterwards, an answer that quietly used a search looked identical to
one the model invented.

A `tool` SSE event now sits between `started` and the first `delta`, carrying
the tool id and the query. The UI renders it above the answer and **keeps it
there**: "this was searched" matters more once the text is on screen than during
the wait.

The summary is built defensively — models emit malformed JSON often enough that
a caption must never fail a turn — and only recognised fields are surfaced,
rather than echoing arbitrary tool arguments at a user.

### Verification

```
ruff / black / mypy --strict ... clean (142 files)
pytest ....................... 626 passed   (622 before)
vitest ....................... 74 passed    (70 before)

Live, against Tavily + FW-Kimi-K3, asking a question with no instruction
to search:

  [TOOL] internet-search — "latest stable Python version release date"
  159 deltas, cited inline:

  "The latest stable version is Python 3.14, first released on October 7, 2025
   ([Python developer guide](https://devguide.python.org/versions)). The most
   recent patch release is 3.14.7 (August 5, 2026), per endoflife.date."
```

The agent chose to search. That is the behaviour that was asked for, and it also
retires the previous entry's caveat that Tavily had never been called live.

### Known limitations

1. **Tool *results* are not shown**, only the request. Sources reach the user
   through the model's inline citations, which depends on it following the
   prompt. A structured source list would not.
2. **The trace shows what was asked, not what came back**, so a search that
   returned nothing looks the same as one that grounded the whole answer.
3. **Whether to search is the model's judgement.** It will sometimes search
   needlessly and sometimes answer stale. The prompt biases it; nothing enforces
   it.

---

## Milestone 06 — Infrastructure as Code ⚠️

Complete and validated against Azure. **Not provisioned** — `azd up` creates
billable resources, and that is the user's decision to make, not mine. See
"What has not been proven" below.

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Infrastructure deploys with azd | ⚠️ | `az deployment sub validate` passes against the real subscription; `azd up` has not been run |
| All required resources provisioned | ✅ | Declared and compiling: identity, Log Analytics, App Insights, Key Vault, ACR, Container Apps environment, two Container Apps, AI Foundry account + model deployment |
| Managed Identity configured | ✅ | User-assigned, with `AcrPull`, `Key Vault Secrets User` and `Cognitive Services User`; the apps carry it and pull images with it |
| Application Insights connected | ✅ | Connection string written to Key Vault and read by the backend as a secret reference |
| Environment-specific parameters | ✅ | Four typed `.bicepparam` files, all compiling in CI |
| No manual portal configuration | ✅ | Nothing outside `az login` |

### What was built

Milestone 01 left a scaffold — identity, monitoring, vault, registry, Container
Apps environment. This milestone completes the graph: the AI Foundry account and
model deployment, both Container Apps, and the secret plumbing between them.

Three decisions worth stating:

**Keys are disabled, not merely unused.** The Foundry account sets
`disableLocalAuth: true`, so an API key cannot be used even by someone who wants
to. That closes the "key copied into a repository" incident at the resource
rather than by convention — which matters, because it happened twice in this
project's own history.

**No secret crosses a module boundary or a deployment output.** Milestone 01
promised the Application Insights connection string would never be an output;
`telemetry-secret.bicep` keeps that promise by reading it and writing it to Key
Vault inside one scope. `main.bicep` learns the secret's URI and nothing more.
Both container secrets are Key Vault references resolved by the managed identity
at revision start, so they are absent from the app's environment definition too.

**Environments differ in capacity and posture, not in shape.** One template,
four parameter files. Testing provisions no inference resource at all, because
nothing there calls a model and idle capacity buys nothing.

### Defects found while building, and fixed

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| **The deployed frontend would have called `http://localhost:8000`.** Vite bakes its API URL into the bundle at *build* time and the Dockerfile's default is localhost; nginx does not proxy the API. Every request from a user's browser would have gone to their own machine, and it would have looked like a CORS fault. | Reading the Dockerfile instead of assuming the frontend read configuration at runtime | `azure.yaml` passes `SERVICE_BACKEND_URI` as a Docker build argument. Works only because azd provisions before it builds |
| With no Foundry account the template still declared the provider enabled with an empty endpoint. The backend's own startup validation would have refused to boot — correctly, and only after a full deployment. | Writing the testing environment's parameters, which deliberately has no inference resource | `foundryEnabled` drives the provider, model id and mock flag together |
| The Application Insights connection string was not available as a module output — by a deliberate Milestone 01 decision I had forgotten | `bicep build` failed | A module that reads and writes it within one scope, honouring the original decision rather than working around it |
| CI compiled the templates but never the environment parameter files | Adding the files | A CI step that builds all four |

The first is the one worth remembering: it would have produced a deployment that
provisioned cleanly, reported healthy, and did not work.

### Verification performed

```
az bicep build ................ main.bicep and 8 modules compile, no warnings
az bicep build-params ......... all 4 environment files compile
az deployment sub validate .... PASSED against the real subscription
az deployment sub what-if ..... resolves 5 top-level creates (see below)
infra/scripts/preflight.sh .... run against the real subscription, all checks pass
preflight.ps1 ................. parses cleanly

pytest ........................ 626 passed (unchanged — no application code changed)
ruff / black / mypy --strict .. clean
```

### What has not been proven

**`azd up` has never been run.** Everything above is static validation plus
Azure's own template validator. That is the strongest evidence available without
spending money, and it is genuinely weaker than a deployment:

1. **`what-if` resolved only 5 changes.** It does not expand nested modules whose
   inputs depend on runtime values, so most of the graph is unverified by it.
   This is a what-if limitation, not a signal that the resources are missing.
2. **The Fireworks model deployment may need a marketplace agreement** that
   Bicep cannot accept on your behalf. The existing FW-Kimi-K3 deployment was
   created through the portal, which handles that step.
3. **Quota is unknown** for `DataZoneStandard` capacity 25 in a new account.
4. **Container Apps Key Vault references** are declared correctly but unexercised;
   a wrong identity or a missing role shows up as a revision that will not start.

Given this project's own record — every milestone so far has had at least one
defect that only a live call could find — the honest expectation is that the
first `azd up` surfaces something.

### Known limitations

1. **No CI/CD.** Deployment is a command someone runs. Milestone 07.
2. **No VNet.** Public ingress with TLS. A Milestone 08 hardening step, and a
   parameter change rather than a redesign.
3. **`traceSampleRatio` is an `int`**, so a fractional sampling ratio cannot be
   set from a parameter file. Production wants 0.2. Needs the parameter type
   changed to `string` and parsed, or ARM's `json()` used.
4. **No blue/green and no multi-region** — both explicitly out of scope.
5. **The identity cannot be granted a role on a Foundry account it does not
   create**, so `PROVISION_AI_FOUNDRY=false` needs one manual role assignment.

---

## Milestone 07 — DevSecOps and CI/CD ⚠️

CI is green on real runners, verified over five runs. CD is written and
unexecuted — it deploys to Azure, which nothing has provisioned yet.

### The finding that mattered most

**CI had never run. Not once, across six milestones.**

Its triggers were `push` to `main` and pull requests to `main`. Every commit in
this project's history has been on a long-lived feature branch with no pull
request, so `gh run list` returned nothing at all. Six milestones of "CI passes"
meant "the same commands passed on one Windows laptop".

That is precisely the gap CI exists to close, and it had been open the entire
time. Triggers now include feature branches.

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Pull requests execute CI | ✅ | Five runs on a real runner; the last fully green |
| Docker images build | ✅ | Built, started and probed on `/live` and `/healthz` in CI |
| Bicep validates | ✅ | Templates and all four parameter files, in CI |
| Security scans execute | ✅ | Trivy filesystem and both images; CodeQL configured |
| Images publish to ACR | ⚠️ | Written and unrun — there is no registry until something is provisioned |
| Deployment supports 4 environments | ⚠️ | Written and unrun, for the same reason |

### What running it actually found

Five runs. Every one found something that no amount of local checking had.

| # | Finding | Why local checks missed it |
| --- | --- | --- |
| 1 | **`aquasecurity/trivy-action@0.28.0` does not exist** — the tags carry a `v` prefix. Present since Milestone 01, so every security scan the repository claimed to run was a step that could not resolve. | Nothing evaluates an action reference until a runner tries to |
| 2 | `rhysd/actionlint` has no `fail-on-error` input | Mine, from the same commit |
| 3 | **SC2044**, a `for` loop over `find` output | actionlint passed locally and failed on the runner: the runner has shellcheck, this machine does not, so the local check was quietly weaker |
| 4 | Trivy's own install script failed on the runner | It is fetched at run time from a moving branch; nothing here could pin it. Replaced with the published image |
| 5 | SC2086, and CodeQL refusing two SARIF runs under one category | Only visible on a runner |
| 6 | **35 image vulnerabilities, 2 CRITICAL** — CVE-2026-31789, an OpenSSL heap overflow, in the nginx base | The images had never been scanned, because of finding 1 |

The last is the one to remember. A security gate that cannot resolve its own
action reports nothing and looks identical to a gate that found nothing.

### What was built

Quality gates and container builds are reusable workflows called by both CI and
CD, so a release cannot pass checks a pull request would fail. Duplicated they
drift, and the drift always favours the release pipeline — that is the one under
time pressure.

`cd.yml` provisions, publishes and deploys one environment, then smoke tests it
against `/ready` rather than `/live`. Liveness passes before the platform can
answer, so a liveness-only check produces a green deployment that serves errors,
and nobody investigates a green pipeline.

Authentication is OIDC federated credentials throughout — no service principal
secret exists in this repository. The same argument that removed API keys from
the application, applied to the pipeline.

Deployment is manual. This platform bills per model call and per provisioned
throughput, and an accidental production deployment is not recoverable by
reverting a commit.

### Verification performed

```
CI run 1 ... 3 failures: unresolvable action ×2, shellcheck SC2044
CI run 2 ... 2 failures: Trivy install script, then its fallout
CI run 3 ... 2 failures: SC2086, duplicate SARIF category
CI run 4 ... 1 failure:  the image gate, finding real CVEs
CI run 5 ... ALL GREEN — quality, images, infrastructure, security

actionlint ... clean on all five workflows
pytest ....... 626 passed, on the runner as well as locally
```

### Known limitations

1. **CD has never run.** It needs provisioned Azure resources, federated
   credentials and GitHub Environments — none of which exist yet. Given this
   project's record, expect the first run to find something.
2. **Federated credentials, secrets, environments and branch protection are all
   manual one-time setup.** Documented in `docs/runbooks/ci-cd.md`; none of it
   can be committed.
3. **CodeQL has not run** — it triggers on `main` and pull requests, and there
   has been neither.
4. **`main` is unprotected**, so `CI` is not yet a required check.
5. **`apt-get upgrade` in the image build means two builds of one commit can
   differ.** Deliberate: a reproducible build of a vulnerable image is not worth
   much. It does weaken "the image that was verified is the image that ships"
   for anything rebuilt later.
6. **No deploy-on-merge, no blue/green, no canary, no release automation.**

---

## Milestone 08 — Production Hardening and Operational Readiness ⚠️

Resiliency and observability are built and tested. The operational procedures
are written and **undrilled** — see "What is written but unproven".

### Acceptance criteria

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Health probes succeed | ✅ | `/live`, `/ready`, `/health` measured; `/health` reports every component with detail |
| Logs and traces visible | ✅ | Structured logs with correlation IDs throughout; App Insights wired via Key Vault reference |
| Retry, timeout and circuit breaker | ✅ | Circuit breaker implemented and tested — 27 tests |
| Alert rules documented | ✅ | Six rules as Bicep, severity-graded, compiling |
| Performance meets targets | ✅ | Baseline **measured**, not asserted — table below |
| Cost metrics captured | ✅ | Tokens, latency and cost on every call; a spend alert |
| Backup strategy documented | ✅ | `backup-recovery.md`, including that there is nothing to back up and why that is a stage rather than an achievement |
| Rollback documented | ✅ | `ci-cd.md` — a revision traffic switch, seconds |
| Dashboards populated | ❌ | No environment exists to populate one. KQL queries are in the runbooks instead |

### The circuit breaker

The milestone's real engineering. `architecture.md` §23 listed it as future
work; this is that work.

Retry and a breaker solve opposite problems, and having only the first is worse
than it looks. Retry assumes failure is transient and retrying is cheap. When a
provider is genuinely down both assumptions invert: every request pays the full
timeout three times, and the retries become load on something already
struggling. A user waits three minutes to learn what the first attempt knew.

Five consecutive counted failures open the breaker for 30 seconds, then one
trial request decides whether to close it. Per provider, never global — a shared
breaker would let one provider's outage stop calls to a healthy one.

**Validation failures never count.** They are the caller's fault, and a stream
of malformed requests must not cut off a healthy provider for everyone else.

Checked *inside* the retry loop rather than once before it, so a breaker that
opens partway through stops the remaining attempts. Tested: with a threshold of
2 and 5 permitted attempts, the provider is called twice.

### Performance baseline — measured

Against the mock provider with telemetry off, so this is the platform's own
overhead. The model dominates a real turn so completely that it hides
everything else, and model latency is a fact about the model.

| Path | p50 | p95 | p99 |
| --- | --- | --- | --- |
| `GET /live` | 0.85 ms | 1.23 ms | 1.69 ms |
| `GET /health` | 1.15 ms | 1.95 ms | 2.17 ms |
| `POST /chat/messages` | 4.37 ms | 4.89 ms | 5.39 ms |
| Streaming, first token | 4.58 ms | 35.1 ms | 35.1 ms |

The streaming p95 is one unwarmed iteration, not a tail.

**Conversation length costs nothing measurable.** Turn 21 came back faster than
turn 2 — 4.32 ms against 5.02 ms, which is noise. Session memory is bounded and
in-process, so history does not accumulate cost.

No tuning was needed, and none was done. Inventing an optimisation for a path
that answers in four milliseconds would have been work performed to have
performed work.

### Defects found while building

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| `provider_id` passed explicitly alongside `**context.to_log_fields()` — a duplicate keyword argument, so a `TypeError` on the one path that only runs when a provider is already failing | The breaker's own tests | Removed. This is the third instance of this exact mistake in the project |
| `ScriptedProvider`, my test double, was narrower than `LLMProvider` and failed on `estimate_cost` | Running the gateway tests | Implemented the whole protocol, plus a test asserting the double satisfies it so it cannot drift back |
| `ErrorCategory.POLICY` does not exist; it is `POLICY_VIOLATION` | mypy | Corrected |

The second is the recurring one, and it now has a guard rather than another
resolution to be careful.

### Verification performed

```
ruff / black / mypy --strict ... clean (145 files)
pytest ....................... 649 passed   (626 before)
                               27 new: breaker states, transitions, gateway
                               integration, retry interaction
az bicep build ............... main + 9 modules, alerts included
az bicep build-params ........ all 4 environments
benchmark .................... run, numbers above
```

### What is written but unproven

Every operational procedure here is theory. Nothing has been drilled, because
nothing is deployed.

1. **The alert rules have never fired.** They compile. Whether their KQL matches
   the log shape this platform actually emits is unverified, and a query that
   silently matches nothing looks exactly like a healthy system.
2. **The recovery procedure has never been executed.** A recovery procedure
   nobody has run is a hypothesis. It should be drilled deliberately, before it
   is needed.
3. **No load testing.** The baseline is single-threaded latency, not throughput
   under concurrency. Scaling numbers are starting points, not measurements.
4. **No dashboard.** There is no environment to populate one from. The runbooks
   carry KQL queries instead, which is less pretty and more portable.

### Known limitations

1. **Conversation memory is still in-process.** It does not survive a restart
   and is not shared between replicas, so a scaled-out deployment can lose a
   user's history mid-conversation. The largest remaining gap, and the one that
   would change `backup-recovery.md` from "nothing to back up" to a real
   procedure.
2. **No provider failover.** The breaker fails fast; it does not fall back.
   With one provider, an open breaker means certain failure — which is why it
   can be disabled.
3. **Cost reports zero** until per-model rates are configured.
4. **No DR and no multi-region.** Explicitly out of scope. A region outage means
   an outage.

---

## Milestone 09 — Enterprise Expansion ⚠️ substantially complete

**Six of the milestone's capabilities are delivered. What remains is recorded
below with reasons, not quietly dropped.**

Delivered: multi-agent collaboration, long-term memory, policy-driven model
routing, MCP tools, RAG with embeddings and a vector store, and evaluation
metrics with cost analytics.

Deferred: knowledge graph, RBAC and governance (explicitly deferred by
`CLAUDE.md`), and the product surfaces — marketplace, scheduler, workflow
designer, dashboards.

**The original scope note, kept because the reasoning still applies.**

Milestone 09 as written is nine subsystems: multi-agent orchestration, MCP,
RAG, embeddings, vector stores, knowledge graphs, long-term memory, model
routing, governance, approvals, analytics and a marketplace. That is not one
milestone's work. Nine packages each three-quarters built would satisfy the
checklist and leave the platform worse than not starting them — every one would
need revisiting before it could be trusted, and none would be finishable
without first understanding what the last person left half-done.

That judgement stood: the milestone was taken one capability at a time, each
finished and verified before the next was started, rather than nine started
together. Six are now complete; the rest are below with their reasons.

### Multi-agent collaboration ✅

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Multiple agents collaborate through the runtime | ✅ | Delegation runs the specialist through `AgentRuntime`; verified end to end |
| Agents never call each other directly | ✅ | Delegation is a tool, so the runtime mediates — `architecture.md` §31 |
| A second agent needs no new code | ✅ | The research agent is a settings block and a prompt asset. `ChatAgent` is generic |
| Cycles are bounded | ✅ | `delegation_depth` on the ExecutionContext; refused at the limit |
| An agent cannot reach what it was not permitted | ✅ | Refused by name, with the real options listed |

The delegation-as-a-tool decision is the one worth keeping. The tool pipeline
already resolves through a registry, checks the caller is permitted, validates
arguments, applies timeout and retry policy, records telemetry and enforces
budgets. Delegation needs every one of those. A parallel mechanism would have
meant implementing them again and getting one subtly wrong.

Cycles were the real problem. A delegates to B delegates to A, and each
individual call looks reasonable. The depth counter rides on the context so it
survives every hop — including into a delegate's own tools — because a counter
held anywhere else resets at exactly the moment a cycle would be caught.

One genuine cycle appeared in the object graph too: the tool registry is built
before the runtime, and the runtime needs the registry. Resolved with a
container self-reference giving the tool a lazy accessor, rather than mutating
a constructed object — which would leave a window where the tool exists and
cannot work.

### Long-term memory ✅

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Conversations survive a restart | ✅ | Real `redis:7-alpine`: a *second client* read back history the first one wrote |
| Conversations are shared between replicas | ✅ | Same test — a new connection is the same proof as a new replica |
| Switching backend is configuration only | ✅ | `MemorySettings.provider`; no agent, runtime or workflow file changed |
| A failed backend does not fail chat | ✅ | Reads degrade to empty, writes are swallowed, health reports DEGRADED |
| Deployable to Azure | ✅ | `modules/redis.bicep`; template compiles, all four `.bicepparam` files validate |
| No new secret | ✅ | Entra ID data-plane auth. Nothing in Key Vault, no password in any URL |

**The failure posture is the decision worth keeping.** A memory backend that is
down must not take chat down with it. Losing history is visible to the user and
survivable; losing the turn is neither. `health_check` therefore reports
DEGRADED rather than UNHEALTHY — UNHEALTHY would fail readiness and remove a
replica that can still answer every request, turning a degraded cache into an
outage.

**Entra rather than an access key** was the more expensive choice and the right
one. The conventional pattern puts the cache's primary key in Key Vault and
interpolates it into a connection URL; it works, and it means holding a
long-lived credential for a service that does not require one. The cost was a
credential provider with token caching and a refresh margin — and one real sharp
edge: redis-py authenticates on *connect*, not continuously, so Azure closes a
pooled connection when its token expires. Handled with retries and a health
check interval, and documented rather than glossed. See
[ADR-0012](../adr/0012-durable-conversation-memory.md).

**Verified twice, deliberately.** The suite runs on `fakeredis` so CI needs no
server. That was not accepted as sufficient: this project has three recorded
instances of a test double being more accommodating than the real thing, and
durability across a *new connection* is precisely what an in-process fake cannot
honestly demonstrate. Against a real container:

```
health: healthy
stored (cap 4): ['m2', 'm3', 'm4', 'm5']
roles preserved: ['user', 'assistant', 'user', 'assistant']
survives a new connection: ['m2', 'm3', 'm4', 'm5']
after delete: ()
```

**Known limitations.**

1. **Access keys are not disabled on the cache.** Classic Azure Cache for Redis
   has no switch to disable them, unlike Foundry. Nothing in the platform uses
   them, but they exist.
2. **`search` returns recency, not relevance.** The contract permits a
   documented fallback and this is one. Semantic search needs the embedding
   provider and vector index that do not exist yet.
3. **`summarize` returns `None`.** A memory provider that called a model would
   couple storage to inference. The runtime falls back to truncation.
4. **Off by default in every environment except staging and production.** A
   cache bills continuously with no idle state, so durable memory is a
   deliberate purchase per environment.
5. **Not yet exercised in Azure.** The module compiles and the parameters
   validate; no environment has been provisioned with `provisionRedis = true`.

### Policy-driven model routing ✅

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Models are selectable by policy | ✅ | Chain of policies over the catalogue; objective is one setting |
| Selection works per agent and per request | ✅ | Agent's model is the preference; `pinned_model_id` and `objective` override per turn |
| Routing crosses providers | ✅ | Live: `lowest_cost` moved a turn from `azure-foundry` to `mock`, and execution followed |
| A capability mismatch is refused, not ignored | ✅ | A tool-using agent cannot be routed to a model that cannot call tools |
| Every decision is explicable | ✅ | Policy id, reason and ranked runners-up on the decision and the context |
| Nothing silently fails over | ✅ | No fallback model, no failover; withdrawal is `is_available`, which is visible |

**A chain, not a score.** A weighted score is easy to write and hard to operate:
when it picks something unexpected, the answer to "why?" is a number, and the
only remedy is guessing at weights. A chain answers with the *name of the step*
that removed the alternative — `capability`, `context-window`, `availability` —
which is something a person can act on at three in the morning.

**Constraints and rankings are deliberately different.** Constraints remove
models that cannot serve the turn and may refuse. Rankings reorder viable models
and can never refuse. Without that split, asking for the cheapest model could
produce "no model available" — an objective quietly behaving as a second
constraint, which is how operators learn to distrust a router and pin
everything.

**Routing found a real defect on its first run.** `MockLLMProvider` emits tool
calls in both `generate` and `stream`, while `supports()` and `list_models()`
both declared it could not — a claim that went stale when tool calling was added
in Milestone 04 and stayed wrong because *nothing read it*. The moment routing
began filtering on capabilities, every tool-using turn became unroutable. Both
providers now compute their capability set once, and a test asserts the two
answers agree for every member of the enum.

That is the argument for capability-based routing in one incident: a declaration
nobody consumes is a declaration nobody maintains.

**`ConfiguredProviderResolver` was deleted, not deprecated.** It ignored
`model_id` entirely — correct with one provider, false the moment routing could
choose another. Keeping it alongside `RegistryBackedProviderResolver` would have
been a second implementation nothing wired, which is exactly how the mock's
capability claim drifted.

### Live verification

Two providers registered, Foundry priced from configuration and the mock free:

```
balanced    -> fw-kimi-k3 on azure-foundry
               The agent's configured model (fw-kimi-k3) is viable.
lowest_cost -> mock-echo on mock          <-- crossed providers
               Cheapest model able to serve the turn (mock-echo).
               considered: ('mock-echo', 'fw-kimi-k3')
               context stamped: model=mock-echo provider=mock
executed    -> 204 chars, served by mock/mock-echo, 710 tokens, cost 0
bad pin     -> refused by policy 'pinned-model'
```

The `served by mock/mock-echo` line is the one that matters: the decision did
not merely get recorded, it changed which provider answered.

**Known limitations.**

1. **The context estimate is a rule of thumb.** Four characters per token, no
   tokenizer. It errs towards under-estimating, which keeps a marginal model
   rather than excluding a workable one — the first failure is reported by the
   provider, the second would be invisible.
2. **`highest_capability` is an approximation.** Breadth of declared
   capabilities. The platform has no quality score, and deriving one from price
   would encode "expensive means good".
3. **No latency-aware routing.** The platform records latency but does not feed
   it back into selection.
4. **Pinning is not on the public API.** Choosing a model is choosing a bill,
   and there is no authorisation layer yet to decide who may.
5. **The chain itself is not configurable**, only the objective. Deliberate: a
   deployment must not be able to remove a constraint by accident.

### MCP tools ✅

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Tools on MCP servers are usable by agents | ✅ | Live: a real server's tool executed through the tool executor |
| Nothing outside the adapter changed | ✅ | Runtime, tool executor, tool loop, workflow engine and agents untouched |
| An agent uses one by configuration alone | ✅ | `tool_ids=("mcp.directory.lookup_employee",)` — no code names it |
| A dead server does not stop the platform | ✅ | Discovery failures are logged and skipped; proven against a refused port |
| Arguments are validated before a remote call | ✅ | `jsonschema` against the server's own schema |
| The SDK is confined to one module | ✅ | `streamable_http_session.py`; everything above speaks platform types |

**The adapter claim from ADR-0010 is now demonstrated rather than asserted.** An
MCP tool is resolved through the registry, validated, timed, retried, logged,
traced and budgeted by exactly the same code path as `internet-search`. The
alternative — a second tool interface — would have meant a second execution path
and every runtime policy implemented twice.

```
registered tools: ('internet-search', 'delegate-to-agent', 'mcp.directory.lookup_employee')
description: Look up an employee in the corporate directory.
schema properties: ['name']
executed: succeeded=True output={'content': 'Vinod works in Platform Engineering, based in Oslo.', ...}
health: healthy — MCP tool 'lookup_employee' on 'directory'
```

**The hardest bug in this milestone, and a fake could never have found it.**
When an MCP server is unreachable, the SDK unwinds its anyio cancel scopes by
cancelling the running task, and what escapes is a bare `CancelledError` —
**indistinguishable** from a caller cancelling the request. Measured on both
paths, `Task.cancelling()` is `1` and `Task.uncancel()` returns `0`.

Before the fix, an unreachable MCP server raised `CancelledError` straight
through discovery's `except PlatformError` and **stopped the platform from
starting** — the exact guarantee the design makes. The fix is structural: each
SDK operation runs in its own task, awaited through `asyncio.shield`, so the
inner task being cancelled means the server is unreachable while this task being
cancelled means the caller stopped us. Both branches are tested against a real
server.

Three earlier attempts were wrong in instructive ways — wrapping only the inner
call, then a hand-written `__aenter__`/`__aexit__` pair (anyio: *"attempted to
exit cancel scope in a different task"*), then `Task.cancelling()` as a
discriminator. None of it is reachable through a fake, which has no connect to
fail.

**Two SDK renames were caught by introspecting the installed package** rather
than writing from memory: `streamablehttp_client` → `streamable_http_client`,
and `inputSchema` → `input_schema`. The second is the dangerous one — reading
the wrong attribute yields an empty schema with no error, and a model told the
tool takes no arguments.

**Known limitations.**

1. **A handshake per tool call.** Sessions are not pooled — see ADR-0014 for why
   pooling was rejected on lifetime correctness, and where it would go.
2. **Streamable HTTP only.** `stdio` means spawning a subprocess inside the
   container; refused at configuration time rather than ignored.
3. **No OAuth.** A configured header only. Who consents, on whose behalf, with
   what audit trail is a governance decision, and `CLAUDE.md` defers
   authorisation.
4. **Discovery is at startup.** A tool added mid-run is not seen until a
   restart; a tool that disappeared is reported by the health check.
5. **No retries.** A remote tool may have side effects and the protocol carries
   no idempotency signal.
6. **Not yet used against a third-party server.** Verified against a real MCP
   server over real HTTP, but one the test suite starts itself.
7. **The MCP integration tests are intermittently flaky in a full-suite run** —
   roughly one run in six, always the same two tests, and never when the file
   runs alone (verified across many consecutive runs). Recorded rather than
   hidden, because three plausible fixes each improved matters without
   eliminating it:

   - the fixture chose a free port and handed it to uvicorn, leaving a window
     for anything else to bind it — uvicorn now binds port 0 and reports back;
   - `list_tools` was not retried, so one dropped connection failed a test —
     it is now retried, being the one idempotent operation;
   - a server was started and stopped per test, fifteen times per run — one
     module-scoped server now serves them all.

   What remains points at MCP session state on the *server* degrading after
   many rapid open/close cycles: the failure is always in the last tests to
   run, and always after a dozen sessions against one server. That churn is a
   property of the harness, not of the platform — production opens one session
   per tool call, spread over time, against a server it does not control. It is
   still a flaky test and it is still counted as an open problem.

### RAG, embeddings and vector store ✅

| Criterion | Status | How it was verified |
| --- | --- | --- |
| A RAG pipeline is operational | ✅ | Live: corpus indexed at startup, queried through the tool executor |
| Documents are chunked on structure | ✅ | Paragraphs, then sentences, then a hard cut; overlapping |
| Embeddings are **semantic** | ✅ | Local ONNX model; paraphrase and synonym tests pass |
| Embeddings are provider-agnostic | ✅ | Local semantic, Azure Foundry and lexical behind one interface |
| A vector store is pluggable | ✅ | `VectorStoreProvider`; in-process exact search first |
| Retrieval is governed by the runtime | ✅ | It is a tool, so authorisation, timeout, retry, telemetry and budget apply |
| Re-indexing is safe | ✅ | Derived record ids replace; orphaned tails are deleted |
| It runs with nothing provisioned | ✅ | `docker compose up` and CI need no model and no database |

**Retrieval is a tool, not a prompt preamble.** That is the decision the whole
slice turns on. The usual pattern — retrieve on every turn and prepend the
passages — spends context on turns that need none, sits outside every runtime
policy, and gives the model no way to say what it searched for. As a tool, the
model decides when documents are needed, an agent that must not see internal
documents simply does not list it, and the query is visible because the model
formulated it.

### Live verification

The repository's own corpus, indexed at startup and queried through the tool
executor:

```
tools: ('internet-search', 'knowledge-search', 'delegate-to-agent')
vectors indexed: 6

query: 'how does agent delegation avoid cycles'
    [0.482] platform-overview.md   # Multi-Agent AI Platform Overview...
query: 'trace sampling telemetry cost'
    [0.515] cost-controls.md       # Cost Controls...
query: 'what is the aubergine harvest forecast'
    [0.463] platform-overview.md   is carried on the execution context...
```

**The third line is the most useful result here, and it is a negative one.** A
question the corpus cannot answer still scored **0.463** — barely below the
genuine matches. That is the "nearest neighbours are always returned" problem in
one line: a vector search has no concept of *irrelevant*, and without a score
threshold those passages reach the model looking exactly like an answer.

It is also a fair measure of the development embedder. Lexical matching gives
any two pieces of English a moderate baseline similarity from shared character
trigrams, which compresses the range between a real match and a bad one. A real
embedding model separates them much more sharply — and `minimum_score` exists to
be tuned once one is in use, which is why its default is `0` rather than a
number that would look authoritative.

**Known limitations.**

1. **Retrieval quality is measured only by example, not by a benchmark.** The
   paraphrase and synonym tests prove the property; there is no evaluation set
   and no recall or precision figures. Judging it properly needs a corpus with
   known answers.
2. **The local model is an optional extra.** `uv sync --extra knowledge` pulls
   ~200 MB of packages and downloads a 67 MB model on first start. The test
   suite still runs on the lexical provider, which is deterministic and needs no
   network; the semantic tests skip without the extra rather than failing.
3. **The vector store is neither durable nor shared.** Rebuilt on every start,
   one copy per replica. The same trajectory memory took, and the same kind of
   change to fix.
4. **No Azure AI Search implementation, and the Foundry embedding provider is
   still unverified against a live endpoint.** No embedding deployment exists
   on the Foundry resource — creating one was blocked by the permission system.
   The code was written by introspecting the installed SDK rather than from
   memory, but it has not made a real call.
5. **Text formats only.** PDF and DOCX need a parser, and a bad parser loses
   structure invisibly.
6. **No reranking, hybrid search or query rewriting.** Each is a real
   improvement and a separate decision.

### Evaluation metrics and cost analytics ✅

| Criterion | Status | How it was verified |
| --- | --- | --- |
| Every model invocation emits evaluation metadata | ✅ | Runtime records after every turn — completed, failed and streamed |
| Metrics are collected | ✅ | Provider, model, agent, tokens, cost, latency, success |
| Cost is queryable | ✅ | `GET /api/v1/analytics/costs`, grouped by model, provider and agent |
| Cost is **visible in the UI** | ✅ | Spend card on the overview, full breakdown at `/cost` |
| Telemetry cannot fail a request | ✅ | Every sink swallows; the composite enforces rather than trusts |
| Adding a durable sink is additive | ✅ | One line in the composite's tuple |
| No user content is recorded | ✅ | Counts, identifiers and money only — asserted against captured output |

**Cost analytics is an `EvaluationProvider`, not a special case.** That is what
lets the runtime record once, to one port, without knowing how many things
listen. A second sink — Application Insights, Cosmos DB — is a line in a tuple.

**Failed and abandoned turns are recorded**, which is the decision most easily
got wrong by accident. Counting only successes flatters the platform exactly
when it is misbehaving: an incident where half of requests fail would show
unchanged cost and improving latency. A failed turn often consumed tokens, and
those were billed.

**A live run caught an overclaim in my own comment.** The code said a turn the
consumer abandoned is "still measured". Measured against the real runtime, the
count was unchanged after a `break` and incremented only on `aclose()` —
because breaking out of an `async for` does not run the generator's `finally`.
The behaviour is correct (the SSE layer closes the generator); the comment was
imprecise, and both it and a test now say exactly when the record lands.

**Attribution follows the routing decision**, not the agent's configuration.
With policy routing those differ, and cost attributed to a model that did not
answer is worse than none — it is wrong in a way that looks right.

### Live verification

Three completed turns plus one abandoned stream, through the real container:

```
invocations : 3
failures    : 0
tokens      : 1983 prompt / 705 completion
cost        : 0 (Decimal)
  by model    mock-echo    3 call(s)
  by provider mock         3 call(s)
  by agent    chat-agent   3 call(s)
evaluation health: Recording to: logging-evaluation, cost-analytics
```

The abandoned stream shows as uncounted here precisely because the script broke
out without closing the generator — the finding described above, reproduced.

**Known limitations.**

1. **Totals are per-process and reset on restart.** A live gauge, not a ledger.
   The ledger is the `evaluation.recorded` events in the structured log, which
   survive restarts and cover every replica. The endpoint says so in a `scope`
   field rather than in documentation, because a per-replica figure read as
   platform-wide spend is the easiest way to make a cost dashboard actively
   misleading.
2. **The endpoint has no authorisation.** Spend by model and agent is
   commercially sensitive and this is as open as the rest of the API. It is the
   first endpoint that should be protected when authorisation arrives.
3. **`average_latency_ms` is a mean**, so it says nothing about the tail — which
   is what users notice. Percentiles need the individual records.
4. **Cost is an estimate** from configured prices, never an invoice. An unpriced
   model contributes zero, so it silently reads as free.
5. **No time series.** "Today versus yesterday" needs a durable sink.

### Deferred, and why

| Capability | Why not now |
| --- | --- |
| Knowledge graph | No source data exists to build one from, and entity extraction is a modelling problem rather than a plumbing one |
| RBAC and governance | `CLAUDE.md` says explicitly: "Do not implement authorization now. Ensure architecture supports it." Following that instruction |
| Marketplace, scheduler, workflow designer, dashboards | Product surfaces, each larger than everything delivered in this milestone |

### Live verification

Against `FW-Kimi-K3` and Tavily, asking a research question with no instruction
to delegate:

```
[TOOL] internet-search x4
11,659 prompt / 2,329 completion tokens
5,051-character answer, cited, current
```

**The coordinator chose not to delegate.** It ran four searches itself. That is
the prompt working as written — "do not delegate what you can answer yourself" —
and it means **delegation is proven structurally, not live**. The structural
proof is complete: the tool runs the specialist through the runtime, the depth
guard refuses at the limit, an unlisted agent is refused, and the specialist
also runs as a first-class agent.

Whether a model *chooses* to delegate is prompt engineering, and it is the part
this milestone has least evidence about.

### Verification performed

```
ruff / black / mypy --strict ... clean (147 files)
pytest ....................... 666 passed   (649 before)
                               17 new: delegation, cycle guard, authorisation,
                               failure handling, health
Local deployment ............. running; 2 prompt assets, 2 agents, Tavily and
                               Azure AI Foundry both healthy
```

### Known limitations

1. **Delegation is unproven with a live model choosing it.** The path works;
   the judgement to use it is the model's.
2. **The specialist cannot see the conversation.** Deliberate — it answers one
   self-contained task — but it means a coordinator must restate context, and a
   poorly-phrased task produces a poor answer with no way to ask.
3. **No agent-to-agent streaming.** A delegated turn is non-streaming, so the
   user waits through it in silence beyond the `tool` event.
4. **Delegation cost is reported but not aggregated.** The tool returns the
   specialist's tokens; nothing sums them into a single per-request figure.

---

## Deployment — 2026-08-09

### Local ✅

Running against the real Azure AI Foundry deployment and Tavily.

```
overall: healthy
  file-prompts    healthy   2 prompt asset(s) across 2 prompt(s)
  tavily          healthy   Tavily search API
  azure-foundry   healthy   Configured for deployment 'FW-Kimi-K3'
  session-memory  healthy   0/500 conversations
```

A live research request returned a cited, current answer using four searches.

### Azure ✅ deployed, one manual step outstanding

`azd provision` ran in **3 minutes 59 seconds**, then both services deployed.

```
rg-maap-dev
├── id-maap-fn5j6tm3kbgem              managed identity
├── log-maap-fn5j6tm3kbgem             Log Analytics
├── appi-maap-fn5j6tm3kbgem            Application Insights
├── kv-maap-fn5j6tm3kbgem              Key Vault
├── crmaapfn5j6tm3kbgem                Container Registry
├── cae-maap-fn5j6tm3kbgem             Container Apps environment
├── ca-maap-backend-fn5j6tm3kbgem      backend
└── ca-maap-frontend-fn5j6tm3kbgem     frontend
```

Frontend: <https://ca-maap-frontend-fn5j6tm3kbgem.yellowsky-26c3bab1.centralus.azurecontainerapps.io>
Backend: <https://ca-maap-backend-fn5j6tm3kbgem.yellowsky-26c3bab1.centralus.azurecontainerapps.io>

The environment reuses the existing Foundry account (`PROVISION_AI_FOUNDRY=false`)
rather than provisioning a second billable model deployment.

**Deployed health:**

```
/ready 200,  overall healthy
  file-prompts    healthy   2 prompt asset(s) across 2 prompt(s)
  tavily          healthy   Tavily search API
  azure-foundry   healthy   Configured for deployment 'FW-Kimi-K3'
  session-memory  healthy
```

### What the deployment proved

Three things that had been asserted for milestones and were now actually true:

1. **The Key Vault secret path works.** Tavily reports healthy in Azure, which
   means the `@secure()` Bicep parameter reached the vault and the Container App
   resolved it through the managed identity at revision start. None of that had
   ever executed.
2. **`prompts/` reaches the image.** Two assets, both agents. The Milestone 05
   fix that added `COPY prompts` was verified locally; this is the first time it
   has been verified in a built-and-pushed image.
3. **The frontend build argument works.** The deployed bundle contains the real
   backend URL. Built any other way it would have contained
   `http://localhost:8000` and every browser request would have gone to the
   user's own machine — the defect found while writing Milestone 06.

### What it surfaced

| Issue | Cause | Resolution |
| --- | --- | --- |
| `azd provision` failed in a background shell — "locking .env: context canceled" | azd holds its own auth session and locks the environment file; a detached shell cancelled it | Ran in the foreground. Not a template defect |
| A combined `azd deploy` left the frontend on the placeholder image | The first backend build exceeded the command timeout and was killed mid-run, after the frontend image had been pushed but before its revision was updated | `azd deploy backend` and `azd deploy frontend` separately, 51 s and 33 s |
| Two `/live` and `/healthz` probes returned nothing before returning 200 | Scale-to-zero. `minReplicas: 0` in development, so the first request wakes the revision | Working as designed |

Nothing required a change to the templates, which is the first time in this
project that a first live run of anything has not.

### Verified end to end in Azure ✅

After the role assignment below, the deployed platform answers:

```
POST /api/v1/chat/messages
  model    fw-kimi-k3 / azure-foundry
  tokens   833 prompt / 297 completion
  latency  3,938 ms

POST /api/v1/chat/messages/stream
  [TOOL] internet-search - "latest stable Python version release date"
  192 delta chunks, 3,943 / 479 tokens
  "The latest stable version of Python is 3.14, first released on October 7,
   2025 (Python Developer's Guide, Liquid Web). The most recent maintenance
   release is 3.14.7, published on August 5, 2026 (endoflife.date)."
```

**This closes the claim Milestone 05 has been making since it was written.**
`DefaultAzureCredential` runs identical code under `az login` locally and
Managed Identity in Azure — and until this request only the local half had ever
executed. There is no key in the application, in the image, in the templates or
in the repository, and the deployed platform authenticated anyway.

Tavily also works from Azure, which exercises the whole secret path: a
`@secure()` Bicep parameter, into Key Vault, resolved by the managed identity at
revision start, into a container that never sees the value in its environment
definition.

### The role assignment, and what it cost to apply

Chat returns:

```
Azure authentication failed. ... In Azure, confirm the Managed Identity has the
'Cognitive Services User' role on the Foundry resource.
```

That message is the provider's own error guidance from Milestone 05, and it is
exactly right. Bicep can only grant roles on resources it creates, and this
environment deliberately reuses a Foundry account it does not own.

```bash
PRINCIPAL=$(az identity show -n id-maap-fn5j6tm3kbgem -g rg-maap-dev --query principalId -o tsv)

az role assignment create \
  --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services User" \
  --scope "/subscriptions/8fb7cbfd-6273-4b2a-986c-0c4a4952aecc/resourceGroups/rg-multi-agent-ai-platform/providers/Microsoft.CognitiveServices/accounts/multi-agent-ai-platform-resource"
```

Until it is granted, health is green and chat returns a provider error — which is
the correct behaviour: the health probe reports configuration, and the
configuration *is* correct. Connectivity is proven by the first request, and
that is the request proving it.

**Applying it took three attempts, none of them a platform defect.**

`az role assignment` on Azure CLI 2.85.0 fails with `MissingSubscription`
whenever `--scope` is passed — including a read-only `list`, which is how it was
identified as a CLI defect rather than a permissions problem. `--subscription`
does not help; the flag never reaches the client making the call. The working
form is the ARM API directly:

```bash
az rest --method put --headers "Content-Type=application/json" \
  --url "https://management.azure.com<scope>/providers/Microsoft.Authorization/roleAssignments/<new-guid>?api-version=2022-04-01" \
  --body "@role-assignment.json"
```

`--headers "Content-Type=application/json"` is required — `az rest` does not set
it on a PUT and returns `UnsupportedMediaType` without it. The body belongs in a
file rather than inline, because PowerShell's quoting mangles inline JSON.

**And the assignment alone was not enough.** The backend still returned 401 with
the role in place and every identifier verified correct. The running process had
started before the role existed and had cached the failed credential; restarting
the revision fixed it immediately.

That is worth remembering during an incident: after granting a role to a running
workload, restart it. The configuration being right is not the same as the
process having noticed.

### Cost note

Development scales to zero, so the Container Apps idle cost is nil. Log
Analytics bills per GB ingested. The model deployment is the pre-existing one,
so nothing new is billed for inference capacity.

To remove everything: `azd down --purge` — `--purge` matters, or Key Vault's
soft delete holds the name for 7 days.
