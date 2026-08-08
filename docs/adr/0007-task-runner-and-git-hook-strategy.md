# ADR-0007: Task as the command runner, and Git hooks that share the project's tool versions

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 01.5 — Developer Experience

## Context

Milestone 01 left every command in the developer's head. Running the gates meant
remembering eight invocations across two directories, two of which need
`--frozen` and one of which only works from `src/frontend`. The setup guide
documents them, but documentation of a command is not the same as the command
being runnable, and the two drift.

Two decisions follow from fixing that, and both have real alternatives.

**How commands are named and run.** The milestone document says "Taskfile.yml
(or Makefile)", leaving the choice open.

**How quality gates run before a commit.** Pre-commit is the obvious framework,
but *which* copy of each tool it runs is not obvious at all, and the
conventional answer turns out to be wrong for this repository.

## Decision

### Task, not Make

`Taskfile.yml`, run by [Task](https://taskfile.dev).

The deciding factor is the platform this project is developed on. Windows has no
`make`, and the ways of getting one — Chocolatey's port, MSYS2, WSL, Git Bash's
partial toolchain — each bring a different set of quoting and path behaviours.
A task runner that behaves differently on the platform the primary developer
uses is a task runner nobody trusts. Task is a single static binary with
identical semantics on Windows, macOS and Linux, and its YAML needs no
explanation of tabs, phony targets, or when a rule re-runs.

Task is nonetheless **optional**. `verify_environment.py` reports it as such,
`.vscode/tasks.json` invokes `uv` and `npm` directly, and the setup guide lists
the raw command beside every `task` shorthand. A contributor who declines to
install it loses convenience, not capability.

### Git hooks run the project's own tools

Every language-specific hook is a `repo: local` hook invoked through `uv run` or
`npm`, so `uv.lock` and `package-lock.json` are the only places a tool version is
declared.

This is not the conventional configuration, and it was not the first attempt.
The first version used the standard mirror hooks, `ruff-pre-commit` and
`black-pre-commit-mirror`, each pinning its own `rev`. Running them surfaced the
problem immediately: the hook's ruff 0.8.4 reported a `BLE001` violation on code
that the project's ruff 0.16.2 — the version in `uv.lock`, and therefore the
version CI runs — accepts. The hook would have blocked a commit that the
pipeline would have passed.

That failure mode is worse than having no hook. A gate that rejects correct work
teaches developers to pass `--no-verify`, and a habit of `--no-verify` disables
every other gate too.

### Hooks are split across two stages

| Stage | Hooks | Why |
| --- | --- | --- |
| `pre-commit` | whitespace, secrets, ruff, black, eslint, prettier | Fast and file-scoped. Sub-second on a normal change. |
| `pre-push` | mypy, pytest, tsc, vitest | Whole-project, several seconds each. |

The split exists for the same reason as the version decision: a hook that makes
committing feel slow gets bypassed, and a bypassed hook protects nothing. Push
is the last moment before work becomes visible to anyone else, which is the
right place for the expensive checks.

The hook set is a **subset** of `.github/workflows/ci.yml`, never a superset.

## Alternatives Considered

### Makefile

**Rejected because:** no `make` on Windows, and every workaround changes shell
semantics. Make's real strength — rebuilding targets from file timestamps — is
unused here: every task in this repository is a command to run, not an artefact
to build.

### npm scripts as the single entry point

**Rejected because:** it puts the Python toolchain behind the JavaScript one.
`npm run typecheck` meaning mypy would be actively misleading, and a backend
contributor would need Node installed to run the backend's tests.

### A `dev.py` script in the repository

Tempting: no extra tool at all, and it can call anything.

**Rejected because:** it is a task runner that has to be written and then
maintained — argument parsing, listing, subprocess handling, exit codes, shell
quoting on two platforms. Task is that program, already written, and its
`--list` output stays correct without anyone maintaining it.

### Mirror hooks with `rev` kept in sync by Dependabot

**Rejected because:** it makes correctness depend on a bot's timing. Between a
`uv.lock` update and the corresponding hook bump, the two disagree — which is
exactly the window the observed failure occurred in. Sourcing both from one lock
file removes the window instead of narrowing it.

### Everything on `pre-commit`, nothing on `pre-push`

**Rejected because:** the full suite plus mypy plus tsc plus vitest is several
seconds on every commit. That is enough friction to change behaviour: developers
commit less often, in larger chunks, or with `--no-verify`.

## Consequences

### Positive

- One command, `task bootstrap`, takes a fresh clone to a working environment.
- `task check` runs exactly what CI runs, so a local pass predicts a green
  pipeline.
- Hooks and CI cannot disagree about a tool's version, because there is only one
  declaration of it.
- The Dev Container makes the toolchain executable rather than documented, and
  `verify_environment.py` makes a missing tool a named error instead of a
  confusing one.
- `scripts/` is on `mypy_path` and `pythonpath`, so the developer tooling is
  type-checked and tested like the rest of the codebase.

### Negative

- `pre-commit autoupdate` no longer manages the Python and Node tool versions;
  they move when `uv.lock` or `package-lock.json` moves. This is the intended
  trade, but it does mean `task hooks:update` updates less than its name
  suggests.
- `language: system` hooks require the environment to be set up. A contributor
  who clones and commits before running `task bootstrap` gets a "command not
  found" from the hook rather than a clean skip.
- Task is one more thing to install for the documented commands to work
  verbatim, even though nothing depends on it.
- The Dev Container image pins uv, Task and Bicep versions that will need
  periodic bumping, and nothing yet notices when they go stale.

### Neutral

- `.vscode/` is committed. Workspace settings that make the editor agree with
  the pipeline are project configuration; personal preferences stay in user
  settings, and `.gitignore` excludes `.vscode/*.local.json`.

## Compliance

- `tests/unit/scripts/test_verify_environment.py` and `test_clean.py` cover the
  developer scripts, including the version-comparison case that a naive tuple
  comparison gets wrong.
- `uv run pre-commit run --all-files` and `--hook-stage pre-push` both pass, and
  are the documented way to check the hook set.
- `.pre-commit-config.yaml` carries the version-drift rationale inline, so the
  next person to reach for a mirror hook reads why it was removed.
- The gates in `Taskfile.yml` are the gates in `.github/workflows/ci.yml`. If
  the two ever disagree, the pipeline is authoritative.

## References

- `docs/milestones/milestone-01.5-developer-experience.md`
- `docs/engineering-handbook.md` — Engineering Quality Checklist
- `CLAUDE.md` — DevOps Standards; Local Development First
- [ADR-0001](./0001-python-version-and-toolchain.md) — uv as the Python toolchain
