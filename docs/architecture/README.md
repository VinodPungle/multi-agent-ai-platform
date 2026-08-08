# Architecture documentation

The authoritative architecture design document is
[`.claude/architecture.md`](../../.claude/architecture.md). It is the single
source of truth and must be kept in step with the implementation.

This directory holds supporting material that would make that document unwieldy:
per-milestone views, sequence diagrams for individual workflows, and deployment
topologies.

## Contents

| Document | Purpose |
| --- | --- |
| [`milestone-01-foundation.md`](./milestone-01-foundation.md) | What Milestone 01 actually built, and how the pieces fit |

## Conventions

- **Mermaid for every diagram.** It renders in GitHub and in most editors, and
  it diffs as text — a binary image cannot be reviewed in a pull request.
- **Show the mechanism.** A diagram that only lists boxes adds nothing over the
  directory listing. Show what calls what, in what order, and where the
  boundaries are.
- **Date and scope each document.** A diagram with no milestone attached becomes
  impossible to trust once the code moves on.
- **Update with the code.** A stale diagram is worse than none: it is confidently
  wrong.
