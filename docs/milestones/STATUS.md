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
| 06 | [Infrastructure as Code](./milestone-06-infrastructure-as-code.md) | ⬜ Next | — |
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

## Next: Milestone 06 — Infrastructure as Code

Not started. Awaiting approval before any work begins.
