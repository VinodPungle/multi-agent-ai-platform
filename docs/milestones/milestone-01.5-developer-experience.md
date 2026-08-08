# Milestone 01.5 – Developer Experience (DX)

## Executive Summary
Improve the local developer experience so contributors can clone the repository, set up their environment, and start productive development with minimal manual steps. This milestone follows Repository Foundation and precedes feature implementation.

## Objectives
- Standardize local development
- Reduce onboarding time
- Enforce consistent tooling
- Automate repetitive developer tasks
- Improve code quality before commit

## Business Value
A consistent development environment reduces onboarding effort, prevents environment-specific issues, and improves engineering productivity.

## Prerequisites
- Milestone 01 completed

## In Scope
- Dev Container configuration
- VS Code workspace settings
- Recommended extensions
- Pre-commit hooks
- Task runner (Taskfile.yml or Makefile)
- Local bootstrap script
- Python (uv) environment setup
- npm installation automation
- Launch configurations
- Debug configurations
- EditorConfig
- Git hooks
- Documentation updates

## Out of Scope
- CI/CD pipelines
- Azure deployment
- Production configuration

## Repository Changes

```text
.devcontainer/
  devcontainer.json
  Dockerfile

.vscode/
  extensions.json
  launch.json
  settings.json
  tasks.json

scripts/
  bootstrap.ps1
  bootstrap.sh
  verify-environment.py

.pre-commit-config.yaml
.editorconfig
Taskfile.yml (or Makefile)
```

## Recommended Tooling
### Backend
- uv
- Ruff
- Black
- mypy
- pytest

### Frontend
- Node.js LTS
- npm (or pnpm if standardized)
- ESLint
- Prettier
- Vitest

### VS Code Extensions
- Python
- Pylance
- Ruff
- Docker
- GitHub Copilot
- Claude Code (if installed)
- Azure Tools
- Bicep
- Tailwind CSS IntelliSense
- ESLint
- Prettier
- Markdown All in One

## Implementation Tasks
1. Configure Dev Container.
2. Create workspace settings.
3. Configure launch profiles for backend and frontend.
4. Add pre-commit hooks.
5. Create bootstrap scripts.
6. Create one-command development task (`task dev` or `make dev`).
7. Add environment verification script.
8. Update Developer Setup Guide.

## Acceptance Criteria
- Fresh clone can be started with documented steps.
- Pre-commit hooks execute successfully.
- VS Code recommends required extensions.
- Backend launches in debug mode.
- Frontend launches in debug mode.
- `task dev` (or equivalent) starts local development environment.

## Test Cases
- Fresh developer onboarding
- Dev Container startup
- Bootstrap script execution
- Pre-commit validation
- Launch configuration verification

## Definition of Done
- Developer setup documented
- Bootstrap scripts tested
- VS Code configuration committed
- Local development reproducible
- New contributor onboarding validated

## Suggested Commits
- chore(dx): add dev container
- chore(dx): configure VS Code workspace
- chore(dx): add pre-commit hooks
- chore(dx): add bootstrap scripts

## Exit Criteria
Repository provides a consistent, low-friction development experience and is ready for Milestone 02.
