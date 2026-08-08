#!/usr/bin/env bash
# =============================================================================
# Bootstrap a fresh clone — macOS, Linux, WSL, Dev Container
# =============================================================================
#   ./scripts/bootstrap.sh
#   ./scripts/bootstrap.sh --skip-frontend    # backend only
#   ./scripts/bootstrap.sh --no-hooks         # skip Git hook installation
#
# Idempotent: safe to re-run at any time, and the normal way to recover after a
# dependency change.
#
# Plain shell rather than Python, because it has to run before any Python
# environment exists. `uv` is the one hard prerequisite, and the script fails
# with an install command rather than a stack trace when it is absent.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

SKIP_FRONTEND=0
SKIP_HOOKS=0

for argument in "$@"; do
    case "${argument}" in
        --skip-frontend) SKIP_FRONTEND=1 ;;
        --no-hooks) SKIP_HOOKS=1 ;;
        -h|--help)
            sed -n '2,12p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "Unknown option: ${argument}" >&2
            exit 2
            ;;
    esac
done

step() { printf '\n==> %s\n' "$1"; }

# -----------------------------------------------------------------------------
step "Checking for uv"
# -----------------------------------------------------------------------------
if ! command -v uv > /dev/null 2>&1; then
    cat >&2 <<'MESSAGE'
uv is not installed, and every other step depends on it.

    curl -LsSf https://astral.sh/uv/install.sh | sh

Then reopen your shell and run this script again.
MESSAGE
    exit 1
fi
echo "uv $(uv --version | awk '{print $2}')"

# -----------------------------------------------------------------------------
step "Verifying the toolchain"
# -----------------------------------------------------------------------------
# `--no-project` skips the workspace sync: the environment is checked before it
# is built, which is the whole point of checking it.
if ! uv run --no-project python scripts/verify_environment.py; then
    echo "Environment check failed. Install the tools listed above and re-run." >&2
    exit 1
fi

# -----------------------------------------------------------------------------
step "Creating .env"
# -----------------------------------------------------------------------------
if [[ -f .env ]]; then
    echo ".env already exists — left untouched."
else
    cp .env.example .env
    echo "Created .env from .env.example. Every default works as-is."
fi

# -----------------------------------------------------------------------------
step "Installing Python dependencies"
# -----------------------------------------------------------------------------
uv sync --all-packages

# -----------------------------------------------------------------------------
if [[ "${SKIP_FRONTEND}" -eq 0 ]]; then
    step "Installing frontend dependencies"
    # `npm ci` installs the locked tree exactly, as CI does. It also deletes and
    # recreates node_modules, which is what makes re-running this script a
    # reliable repair rather than a partial update.
    (cd src/frontend && npm ci --no-audit --no-fund)
else
    step "Skipping frontend dependencies (--skip-frontend)"
fi

# -----------------------------------------------------------------------------
if [[ "${SKIP_HOOKS}" -eq 0 ]]; then
    step "Installing Git hooks"
    uv run pre-commit install --install-hooks
else
    step "Skipping Git hooks (--no-hooks)"
fi

# -----------------------------------------------------------------------------
step "Done"
# -----------------------------------------------------------------------------
cat <<'MESSAGE'
Next:

    task dev        backend and frontend with hot reload
    task up         the same stack in Docker Compose
    task check      every gate CI runs

Without Task installed:

    uv run uvicorn agent_platform.api.app:create_app --factory --reload
    cd src/frontend && npm run dev

See docs/developer-setup.md.
MESSAGE
