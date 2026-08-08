# Developer Setup Guide

Everything needed to run, debug and contribute to the Enterprise Multi-Agent AI
Platform locally.

---

## 0. The short version

```bash
git clone <repository-url>
cd multi-agent-ai-platform

./scripts/bootstrap.sh          # macOS, Linux, WSL
.\scripts\bootstrap.ps1         # Windows

task dev                        # backend + frontend, both with hot reload
```

Bootstrap verifies your toolchain, creates `.env`, installs both dependency
trees and installs the Git hooks. It is idempotent — re-run it any time,
especially after pulling a dependency change.

The only thing you need installed first is [uv](https://docs.astral.sh/uv/).
Everything else is either checked and reported, or optional.

Three other ways in:

| Instead of installing a toolchain | Do this |
| --- | --- |
| Open in a **Dev Container** | VS Code → "Reopen in Container". Nothing else to install but Docker. |
| Just run the thing | `docker compose up --build` |
| Read the long version | Continue below. |

---

## 1. Prerequisites

| Tool | Version | Required | Why |
| --- | --- | --- | --- |
| **Git** | 2.40+ | Yes | Version control, and the hooks `pre-commit` installs |
| **uv** | 0.5+ | Yes | Python dependency management. Also installs Python 3.12 for you. |
| **Node.js** | 20 LTS or 22 LTS | Yes | Frontend tooling |
| **npm** | 10+ | Yes | Ships with Node.js |
| **Docker Desktop** | 24+ | No | `task up`, and the container builds CI runs |
| **Task** | 3+ | No | Task runner for every documented command |
| **Azure CLI** | 2.60+ | No | Only from Milestone 05, for `az login` |

You never have to check this table by hand:

```bash
uv run --no-project python scripts/verify_environment.py
```

It reports every tool, its version, and — for anything missing or too old — what
it is needed for and how to install it. Optional tools are reported but never
fail the check. Bootstrap runs it first and stops if something required is
missing.

```bash
# uv — macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# uv — Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

`uv` downloads and manages Python 3.12 itself, pinned by `.python-version`. You
do not need a system Python 3.12, and your system Python is left untouched.

Task is a single binary and is worth the thirty seconds:

```bash
winget install Task.Task              # Windows
brew install go-task/tap/go-task      # macOS
sudo snap install task --classic      # Linux
```

---

## 2. Clone and configure

```bash
git clone <repository-url>
cd multi-agent-ai-platform

./scripts/bootstrap.sh                # or .\scripts\bootstrap.ps1 on Windows
```

Bootstrap does all of the following, and skips anything already done:

1. Verifies the toolchain and stops with a specific error if something is missing
2. Copies `.env.example` to `.env` — existing `.env` files are never touched
3. `uv sync --all-packages`
4. `npm ci` in `src/frontend`
5. Installs the Git pre-commit and pre-push hooks

Options: `--skip-frontend` / `-SkipFrontend` for backend-only work,
`--no-hooks` / `-NoHooks` to leave Git hooks alone.

`.env` is git-ignored and **must never be committed**. Every value in
`.env.example` has a working default, so the defaults run as-is.

### Dev Container

If you would rather install nothing but Docker, open the folder in VS Code and
choose **Reopen in Container**. `.devcontainer/` pins the same Python, uv, Node,
Task, Bicep and Azure CLI versions CI uses, installs the extensions, and runs
bootstrap for you. Ports 8000 and 5173 are forwarded automatically.

---

## 3. Option A — Docker Compose (recommended first run)

```bash
docker compose up --build
```

| | |
| --- | --- |
| Frontend | <http://localhost:5173> |
| Chat | <http://localhost:5173/chat> |
| Backend | <http://localhost:8000> |
| API docs | <http://localhost:8000/docs> |
| Health | <http://localhost:8000/health> |

Chat answers come from the **mock provider**, which generates text locally.
Compose enables it; if you run the backend directly, `.env` does (copy
`.env.example`). Configuration validation refuses to start a staging or
production environment with it enabled.

Both services hot reload: edit a file on the host and the container picks it up.
Source is mounted read-only, so a container can never write into your working
tree.

```bash
docker compose logs -f backend     # follow logs
docker compose ps                  # service health
docker compose down                # stop
docker compose down -v             # stop and drop volumes
docker compose up --build          # rebuild after a dependency change
```

**Port already in use.** Set the host ports in `.env` — nothing else needs
changing, and CORS follows automatically:

```dotenv
BACKEND_PORT=18000
FRONTEND_PORT=15173
```

---

## 4. Option B — run directly (best for debugging)

### Backend

```bash
uv sync --all-packages      # creates .venv with Python 3.12 and installs everything
uv run agent-platform       # starts the API on http://localhost:8000
```

`uv sync` reads `uv.lock`, so you get exactly the versions CI uses.

For auto-reload while developing:

```bash
uv run uvicorn agent_platform.api.app:create_app --factory --reload
```

### Frontend

```bash
cd src/frontend
npm ci                      # installs the locked tree, exactly as CI does
npm run dev                 # starts Vite on http://localhost:5173
```

The frontend reads `.env` from the **repository root**, not from
`src/frontend` — backend and frontend share one configuration file.

---

## 5. Quality gates

Run these before opening a pull request. CI runs the same commands, so a local
pass means a green pipeline.

### With Task

```bash
task check          # every gate below, in the order CI runs them
task format         # fix formatting and safe lint violations in place
task lint
task typecheck
task test
task test:cov
```

`task --list` shows everything available. Each of the tasks below maps to the
raw commands that follow, so Task is a shorthand and never a requirement.

### Backend — from the repository root

```bash
uv run ruff check .        # lint
uv run ruff check --fix .  # lint, auto-fixing what is safe
uv run black .             # format
uv run mypy                # strict type check
uv run pytest              # tests
uv run pytest --cov        # tests with coverage
uv run pytest -m unit      # unit tests only
uv run pytest -m integration
```

### Frontend — from `src/frontend`

```bash
npm run lint
npm run lint:fix
npm run format
npm run typecheck
npm test
npm run test:watch
npm run test:coverage
npm run build
```

### Containers and infrastructure

```bash
docker build -f docker/backend.Dockerfile  --target production -t agent-platform-backend:local  .
docker build -f docker/frontend.Dockerfile --target production -t agent-platform-frontend:local .

bicep build infra/bicep/main.bicep --stdout > /dev/null
```

### Git hooks

Installed by bootstrap. They run the same tools as CI, from the same lock files,
so they cannot disagree with the pipeline — see
[ADR-0007](adr/0007-task-runner-and-git-hook-strategy.md).

| Stage | Runs | Typical cost |
| --- | --- | --- |
| `pre-commit` | whitespace, secret scanning, ruff, black, eslint, prettier | under a second |
| `pre-push` | mypy, pytest, tsc, vitest | a few seconds |

```bash
task hooks:install                        # or: uv run pre-commit install --install-hooks
task hooks:run                            # run every hook against every file
uv run pre-commit run --all-files --hook-stage pre-push
```

If a hook is wrong, fix the hook. `git commit --no-verify` exists, but a habit of
it disables every other gate too — and the pipeline will catch the same thing
five minutes later.

---

## 6. Debugging

### VS Code

`.vscode/launch.json` is committed. Press **F5** and pick a configuration:

| Configuration | Use it when |
| --- | --- |
| **Full stack (backend + frontend)** | The default. API under the debugger, Vite, and a browser attached. |
| Backend: API (reload) | Debugging request handling |
| Backend: API (no reload, breakpoints in startup) | Debugging configuration validation or startup — the reloader runs the app in a child process, so ordinary breakpoints in startup are never hit |
| Backend: current test file | A failing test, with the debugger on it |
| Frontend: Chrome / Edge | Component and hook debugging with source maps |
| Backend: attach to container | The Compose stack rather than a local process |

`justMyCode` is false throughout: when a request behaves unexpectedly the answer
is usually inside FastAPI, Pydantic or Starlette, and a debugger that refuses to
step into them cannot show it.

`.vscode/tasks.json` mirrors the Taskfile for people who did not install Task —
**Ctrl+Shift+B** runs every gate. `.vscode/extensions.json` prompts for the
extensions the toolchain expects on first open.

### Reading the logs

Development uses the `console` renderer, which is human-readable. Set
`PLATFORM_LOGGING__RENDERER=json` to see exactly what a deployed environment
emits.

Every record carries `correlation_id`, `request_id`, `trace_id` and `span_id`.
To trace one request end to end, take the `X-Correlation-ID` response header and
grep for it:

```bash
docker compose logs backend | grep "e7a43d64-63d6-4039-8199-a3960758df49"
```

### Seeing traces locally

Run any OTLP collector and point the platform at it:

```dotenv
PLATFORM_TELEMETRY__OTLP_ENDPOINT=http://localhost:4318
```

```bash
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one:latest
# Jaeger UI: http://localhost:16686
```

Or, for a quick look without a collector:

```dotenv
PLATFORM_TELEMETRY__CONSOLE_EXPORTER=true
```

---

## 7. Troubleshooting

**`Platform configuration is invalid and the application cannot start`**

Working as designed — configuration is validated before startup. The message
names the offending fields. Check them against `.env.example`, remembering that
nested settings use `PLATFORM_<SECTION>__<FIELD>` with a **double** underscore.

Unknown `PLATFORM_*` variables are rejected too. A typo is a startup failure
rather than a setting that silently does nothing.

**`app.debug must be false outside development`**

You set `PLATFORM_APP__ENVIRONMENT` to `staging` or `production` on a machine
configured for development. Either set it back to `development`, or also set
`PLATFORM_APP__DEBUG=false`, `PLATFORM_LOGGING__RENDERER=json` and explicit CORS
origins.

**Port already allocated**

Another process holds 8000 or 5173. Set `BACKEND_PORT` / `FRONTEND_PORT` in
`.env`, or find the process:

```bash
# macOS / Linux
lsof -i :8000
# Windows
netstat -ano | findstr :8000
```

**Chat replies with "No LLM provider is registered"**

The mock provider is off. It defaults to off so that the unsafe state is always
one somebody chose:

```dotenv
PLATFORM_MOCK_PROVIDER__ENABLED=true
```

**The answer appears all at once instead of streaming**

Either the per-chunk delay is zero (`PLATFORM_MOCK_PROVIDER__CHUNK_DELAY_SECONDS`),
or something between the browser and the backend is buffering. The backend sends
`X-Accel-Buffering: no` for nginx; other proxies may need their own setting.

**Frontend shows "Could not reach the platform API"**

The backend is not running, or `VITE_API_BASE_URL` points at the wrong port.
Confirm the backend answers directly (`curl http://localhost:8000/live`), then
check the browser console for a CORS error — the backend allows only the origins
in `PLATFORM_SERVER__CORS_ORIGINS`. Vite inlines `VITE_*` values at build time,
so restart the dev server after changing one.

**`Failed to resolve import "<package>"` in the frontend container, or a native module error**

Both are the same cause: the container's `node_modules` are stale. Compose mounts
an **anonymous volume** over `/app/node_modules` (see `docker-compose.yml`) so the
host's Windows- or macOS-built modules cannot shadow the container's Linux-built
ones. That volume **survives `docker compose up --build`** — Compose reattaches
the existing one, so a newly added dependency is present in the rebuilt image and
still invisible at runtime.

The `-v` is the part that matters:

```bash
docker compose down -v      # drops the anonymous node_modules volume
docker compose up --build
```

`down` without `-v` reattaches the stale volume and reproduces the error exactly.

**Any time you add a frontend dependency**, that pair of commands is the Compose
equivalent of `npm install`. Running the frontend directly (`task dev`) needs only
`npm ci`, because there is no volume in the way.

**`uv sync` fails to find Python 3.12**

```bash
uv python install 3.12
```

**`task: command not found`**

Task is optional and not installed. Either install it (§1) or use the raw
commands — every `task` shorthand in this guide is documented beside the
commands it runs.

**A pre-commit hook fails with "command not found"**

The hooks run the project's own tools through `uv` and `npm`, so the environment
has to exist first:

```bash
./scripts/bootstrap.sh
```

**Pre-commit changed my files and the commit aborted**

Working as designed. The formatting hooks fix what they can and stop the commit
so you can see what changed. Review the changes, `git add` them, and commit
again.

**Tests pass locally but fail in CI**

Usually a stale lock file. CI runs `uv sync --frozen` and `npm ci`, both of which
fail on lock drift:

```bash
uv lock                          # refresh uv.lock
cd src/frontend && npm install   # refresh package-lock.json
```

Commit both lock files.

---

## 8. Contributing

Read [`engineering-handbook.md`](engineering-handbook.md) before your first pull
request.

**Branches:** `feature/<name>`, `fix/<name>`, `docs/<topic>`,
`refactor/<component>`, `infra/<component>`.

**Commits:** small, focused, meaningful. Never mix unrelated changes.

**Every feature needs** interfaces, dependency injection, externalised
configuration, structured logging, OpenTelemetry spans, unit tests, integration
tests where applicable, documentation, and error handling. No exceptions — this
is the Definition of Done in the PR template.

**Model calls go through the LLM Gateway.** Business logic depends on
`LLMGateway`, never on `LLMProvider`, and no vendor SDK is imported outside
`agent_platform/providers/`. See
[ADR-0006](adr/0006-llm-gateway-and-provider-neutral-contract.md).

**Architecture changes need an ADR.** If a change conflicts with
`.claude/architecture.md`, stop and raise it. Architecture is never changed
silently.

---

## 9. Azure (Milestone 05+)

Not required yet. Azure services are reached with `DefaultAzureCredential`, so
local development authenticates through the Azure CLI and needs no API key:

```bash
az login
az account set --subscription <subscription-id>
```

The same code runs in Azure under Managed Identity, unchanged. Deployment
(`azd up`) lands in Milestone 06; see [`../infra/README.md`](../infra/README.md).
