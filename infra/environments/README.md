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

## Populated in Milestone 06

| File | Model | Search | Min replicas | Retention |
| --- | --- | --- | --- | --- |
| `development.bicepparam` | Foundry | duckduckgo | 0 | 30 days |
| `testing.bicepparam` | none — mock | mock | 0 | 30 days |
| `staging.bicepparam` | Foundry | tavily | 1 | 60 days |
| `production.bicepparam` | Foundry | tavily | 1 | 90 days |

CI compiles all four on every pull request, so a file referencing a parameter
the template no longer has fails review rather than a deployment.

Numeric parameters live here rather than in `main.parameters.json`: azd
substitutes environment variables as strings, and ARM rejects a string for an
`int`. A `.bicepparam` file is typed and checked at build time.

## Rules for when they land

1. **Never commit a secret.** These files hold sizes, SKUs, regions, retention
   and feature toggles. Secrets belong in Key Vault, referenced by name.
2. **Production differs deliberately.** Purge protection enabled, a Premium
   registry with retention, zone redundancy, longer log retention. Each
   difference is a decision, not a default.
3. **Every value is explicit.** A production file must not inherit a development
   default by omission — the point of the file is that its settings were chosen.
