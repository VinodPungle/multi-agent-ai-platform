# Codex Prompt — M11 Approval, Events and Tool Authorization

Repository: `multi-agent-ai-platform`
Milestone: `docs/milestones/M11-approval-events-tool-authorization.md`

Before coding:
1. Read the referenced milestone document.
2. Inspect actual implementation and relevant architecture/ADR documents.
3. Read `docs/internal-fitments/internal-fitments-architecture-assessment.md` if present.
4. Implement ONLY this milestone.
5. Keep platform/business boundaries intact.
6. Use the platform Agent Runtime/LLM Gateway for LLM execution.
7. Preserve provider neutrality and configuration-driven model selection.
8. Keep business state authoritative.
9. Enforce authorization outside the LLM.
10. Protect side effects with idempotency and audit.
11. Do not implement future phases.

After coding:
- run relevant tests/lint/type checks
- review git diff and git status
- report changed files, tests/results, ADR/docs changes, deferred work and risks
- do not commit or push unless explicitly requested.


Prerequisite: M10 complete and green.

Implement M11 only. Inspect existing approval/event/tool/authorization capabilities. Add reusable approval lifecycle, event/background jobs, retry/recovery, tool capability classification, authorization outside the LLM and idempotency. Do not add Internal Fitments concepts. Update tests/docs/ADRs. Stop after M11.
