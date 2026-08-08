<!--
Mirrors the Pull Request Template in docs/engineering-handbook.md.
Delete a section only when it genuinely does not apply, and say why.
-->

## Summary

<!-- What changed, in one or two sentences. -->

## Motivation

<!-- Why this change is needed. Link the milestone or issue. -->

## Architecture Impact

<!--
Which layers are touched? Any new interface, registry, factory or provider?
If this changes architecture, link the ADR. Never change architecture silently.
-->

## Interfaces Added / Changed

<!-- New or modified SDK contracts. Note any breaking change and its migration path. -->

## Tests

<!-- Unit, integration and end-to-end coverage added. -->

## Documentation

<!-- Architecture doc, ADR, handbook, README, milestone status. -->

## Configuration Changes

<!-- New settings, new environment variables, .env.example updates. -->

## Deployment Impact

<!-- Infrastructure changes, migrations, ordering constraints. -->

## Rollback Strategy

<!-- How to undo this if it misbehaves in production. -->

## Risks

<!-- What could go wrong, and what would detect it. -->

---

## Definition of Done

- [ ] Architecture follows Clean Architecture and the documented layer boundaries
- [ ] Interfaces defined; no business logic depends on a provider SDK
- [ ] Dependency injection used; nothing constructs infrastructure directly
- [ ] Configuration externalised and strongly typed
- [ ] Structured logging added, with no secrets or user data logged
- [ ] OpenTelemetry spans added where applicable
- [ ] Unit tests written
- [ ] Integration tests written (where applicable)
- [ ] Documentation updated
- [ ] Ruff, Black, mypy and pytest pass
- [ ] ESLint, TypeScript and Vitest pass
- [ ] Security considered
- [ ] Cost implications considered
