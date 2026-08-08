# =============================================================================
# Backend image — Enterprise Multi-Agent AI Platform
# =============================================================================
# Build context is the repository root, because the backend is one member of a
# uv workspace and needs its siblings' manifests to resolve.
#
#   docker build -f docker/backend.Dockerfile -t agent-platform-backend .
#
# Targets:
#   development  — dependencies plus source mounted at run time, hot reload
#   production   — minimal runtime, non-root, no build tooling  (default)
# =============================================================================

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1 — base
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

# PYTHONDONTWRITEBYTECODE: a read-only filesystem cannot host .pyc files, and
#   caching them in a layer that is rebuilt every deploy buys nothing.
# PYTHONUNBUFFERED: without it, stdout is block-buffered when not a TTY and log
#   records are lost when a container is killed.
# PYTHONFAULTHANDLER: dumps a Python traceback on a fatal signal, which is the
#   only diagnostic available for a segfault or an OOM kill.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# -----------------------------------------------------------------------------
# Stage 2 — dependencies
# -----------------------------------------------------------------------------
FROM base AS dependencies

COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Manifests first, source second. Dependency resolution then re-runs only when a
# manifest changes, not on every source edit — the difference between a
# two-second and a two-minute rebuild during development.
COPY pyproject.toml uv.lock ./
COPY src/backend/pyproject.toml ./src/backend/
COPY src/sdk/pyproject.toml ./src/sdk/
COPY src/shared/pyproject.toml ./src/shared/

# The workspace members are declared as dependencies, so their package
# directories must exist for resolution to succeed. Real source arrives later.
RUN mkdir -p src/backend/agent_platform src/sdk/agent_platform_sdk src/shared/agent_platform_shared \
 && touch src/backend/agent_platform/__init__.py \
          src/sdk/agent_platform_sdk/__init__.py \
          src/shared/agent_platform_shared/__init__.py \
 && touch src/backend/README.md src/sdk/README.md src/shared/README.md README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

# -----------------------------------------------------------------------------
# Stage 3 — development
# -----------------------------------------------------------------------------
FROM dependencies AS development

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace

COPY src/shared ./src/shared
COPY src/sdk ./src/sdk
COPY src/backend ./src/backend

# Editable installs, so a bind-mounted source edit takes effect without a
# rebuild. Compose overlays the host directories over these paths.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# Raw uvicorn here rather than the platform entry point, because only the CLI
# offers `--reload`. Uvicorn installs its own log handlers at startup;
# `configure_logging` then clears them and re-enables propagation, so records
# still flow through the structlog pipeline rather than appearing twice in two
# different formats.
CMD ["uvicorn", "agent_platform.api.app:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/src", "--no-access-log"]

# -----------------------------------------------------------------------------
# Stage 4 — production
# -----------------------------------------------------------------------------
FROM base AS production

# Non-root by default (handbook, "Container Standards"). A fixed uid/gid keeps
# volume ownership predictable across hosts.
RUN groupadd --gid 10001 platform \
 && useradd --uid 10001 --gid platform --create-home --shell /usr/sbin/nologin platform

COPY --from=dependencies --chown=platform:platform /app/.venv /app/.venv

COPY --chown=platform:platform src/shared/agent_platform_shared ./src/shared/agent_platform_shared
COPY --chown=platform:platform src/sdk/agent_platform_sdk ./src/sdk/agent_platform_sdk
COPY --chown=platform:platform src/backend/agent_platform ./src/backend/agent_platform

# The venv holds third-party dependencies only (`--no-install-workspace` above);
# our own packages are resolved from source, which keeps the image free of build
# tooling while remaining a single copy of the code.
# PLATFORM_SERVER__HOST: the container must accept connections from outside its
# network namespace. The application default is 127.0.0.1, which is right for a
# developer machine and wrong here, so it is overridden through configuration
# rather than a command-line flag that would contradict the settings model.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/src/backend:/app/src/sdk:/app/src/shared" \
    PLATFORM_SERVER__HOST=0.0.0.0 \
    PLATFORM_SERVER__PORT=8000

USER platform

EXPOSE 8000

# Container Apps and Kubernetes probe /live themselves; this HEALTHCHECK covers
# plain `docker run` and Compose. It targets liveness, never readiness — an
# unreachable dependency must not restart a healthy container.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/live', timeout=2).status == 200 else 1)"

# The platform's own entry point, not raw uvicorn: it loads and validates
# configuration before the server starts, so an invalid configuration produces
# one clear message instead of a container that boots and fails every request.
# Host and port come from configuration, so they are not duplicated here.
CMD ["python", "-m", "agent_platform"]
