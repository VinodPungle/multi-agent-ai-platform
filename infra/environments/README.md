# Environment parameter files

Per-environment Bicep parameter files live here, one per environment:

```
development.bicepparam
testing.bicepparam
staging.bicepparam
production.bicepparam
```

Each environment must have **independent configuration, independent resources,
independent secrets and independent monitoring** (`CLAUDE.md`, "Environment
Strategy").

## Not yet populated

Milestone 01 provisions nothing, so there is nothing to parameterise. The files
arrive in Milestone 06 alongside the first real deployment.

Creating empty files now would suggest a deployment path exists that does not.

## Rules for when they land

1. **Never commit a secret.** These files hold sizes, SKUs, regions, retention
   and feature toggles. Secrets belong in Key Vault, referenced by name.
2. **Production differs deliberately.** Purge protection enabled, a Premium
   registry with retention, zone redundancy, longer log retention. Each
   difference is a decision, not a default.
3. **Every value is explicit.** A production file must not inherit a development
   default by omission — the point of the file is that its settings were chosen.
