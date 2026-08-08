# Developer Setup Guide

Everything needed to run, debug and contribute to the Enterprise Multi-Agent AI
Platform locally.

---

## 1. Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| **Docker Desktop** | 24+ | The Compose path needs nothing else installed |
| **Git** | 2.40+ | |
| **uv** | 0.5+ | Python dependency management. Also installs Python 3.12 for you. |
| **Node.js** | 20 LTS or 22 LTS | Frontend tooling |
| **Azure CLI** | 2.60+ | Only from Milestone 05, for `az login` |

Only Docker and Git are needed for the Compose path. `uv` and Node are needed to
run the services directly, which is what you want for debugging.

```bash
# uv — macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# uv — Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

`uv` downloads and manages Python 3.12 itself, pinned by `.python-version`. You
do not need a system Python 3.12, and your system Python is left untouched.

---

## 2. Clone and configure

```bash
git clone <repository-url>
cd multi-agent-ai-platform
cp .env.example .env
```

`.env` is git-ignored and **must never be committed**. Every value in
`.env.example` has a working default, so the defaults run as-is.

---

## 3. Option A — Docker Compose (recommended first run)

```bash
docker compose up --build
```

| | |
| --- | --- |
| Frontend | <http://localhost:5173> |
| Backend | <http://localhost:8000> |
| API docs | <http://localhost:8000/docs> |
| Health | <http://localhost:8000/health> |

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

---

## 6. Debugging

### Backend in VS Code

Milestone 01.5 adds `.vscode/launch.json`. Until then:

```jsonc
{
  "name": "Backend",
  "type": "debugpy",
  "request": "launch",
  "module": "uvicorn",
  "args": ["agent_platform.api.app:create_app", "--factory", "--reload"],
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/.env",
  "justMyCode": false
}
```

`justMyCode: false` lets you step into FastAPI and Pydantic, which is usually
where the answer is when a request behaves unexpectedly.

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

**Frontend shows "Could not reach the platform API"**

The backend is not running, or `VITE_API_BASE_URL` points at the wrong port.
Confirm the backend answers directly (`curl http://localhost:8000/live`), then
check the browser console for a CORS error — the backend allows only the origins
in `PLATFORM_SERVER__CORS_ORIGINS`. Vite inlines `VITE_*` values at build time,
so restart the dev server after changing one.

**Frontend container fails with a native module error**

Host `node_modules` have leaked into the container. Rebuild:

```bash
docker compose down -v
docker compose up --build
```

**`uv sync` fails to find Python 3.12**

```bash
uv python install 3.12
```

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
