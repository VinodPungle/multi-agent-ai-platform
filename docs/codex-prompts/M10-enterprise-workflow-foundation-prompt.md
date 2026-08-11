# Codex Prompt — M10 Enterprise Workflow Foundation

Repository: `multi-agent-ai-platform`
Milestone: `docs/milestones/M10-enterprise-workflow-foundation.md`

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


Implement M10 only. Inspect the existing workflow/runtime first. Add only reusable generic durable workflow/checkpoint/resume/retry/timeout/cancellation/recovery/correlation/idempotency capabilities. Do not add Internal Fitments concepts. Update tests and relevant architecture/ADRs. Stop after M10.
