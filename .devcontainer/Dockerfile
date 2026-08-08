# =============================================================================
# Development container image
# =============================================================================
# The environment a contributor gets when they open the repository in a Dev
# Container: every tool the documented workflow needs, at the versions CI uses.
#
# Deliberately separate from `docker/backend.Dockerfile`. That image is what
# ships — minimal, non-root, no build tooling. This one is the opposite: it is
# meant to be lived in, and carries editors' language servers, Git, shell
# completions and the whole test toolchain. Merging them would either bloat the
# production image or starve the development one.
# =============================================================================

# Pinned to the same Python minor version as `.python-version` and the backend
# image. A Dev Container that resolves a different interpreter would produce
# lock-file churn every time someone rebuilt it.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Same uv version as docker/backend.Dockerfile. Copying the binary from the
# official image is faster and more reproducible than running the install
# script, which always fetches the latest release.
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Task: the documented entry point for every command in this repository.
# Version pinned so a rebuild does not silently change the runner's behaviour.
ARG TASK_VERSION=3.40.1
RUN sh -c "$(curl --location --silent --fail https://taskfile.dev/install.sh)" -- \
        -d -b /usr/local/bin "v${TASK_VERSION}" \
 && task --version

# Bicep, for `task bicep` and Milestone 06. The Azure CLI itself arrives as a
# Dev Container feature; this is the standalone binary the lint task uses.
ARG BICEP_VERSION=v0.32.4
RUN curl --location --silent --fail \
        "https://github.com/Azure/bicep/releases/download/${BICEP_VERSION}/bicep-linux-x64" \
        --output /usr/local/bin/bicep \
 && chmod +x /usr/local/bin/bicep \
 && bicep --version

# The uv and npm caches live on named volumes (see devcontainer.json), so they
# survive a container rebuild. Both directories are created here with the right
# ownership, because a volume mounted onto a missing path is created as root and
# every later cache write then fails.
USER vscode
RUN mkdir -p /home/vscode/.cache/uv /home/vscode/.npm

# Shell completion for the tools used dozens of times a day.
RUN echo 'eval "$(uv generate-shell-completion bash)"' >> /home/vscode/.bashrc \
 && echo 'source <(task --completion bash)' >> /home/vscode/.bashrc
