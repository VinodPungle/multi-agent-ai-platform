# Infrastructure scripts

Provisioning and operational helpers that support, but never replace, the
declarative templates.

## Not yet populated

Milestone 01 provisions nothing. Scripts land with the deployments they support:

| Script | Purpose | Milestone |
| --- | --- | --- |
| `preprovision.sh` / `.ps1` | Verify `az login`, subscription and required providers before `azd up` | 06 |
| `seed-key-vault.sh` / `.ps1` | Populate secrets after provisioning, interactively — never from a file | 06 |
| `smoke-test.sh` | Probe `/live`, `/ready` and `/health` after a deployment | 07 |
| `rollback.sh` | Shift Container App traffic to the previous revision | 07 |

## Rules

1. **Declarative first.** A script exists only for what Bicep cannot express —
   verification, secret seeding, post-deployment probes. Anything that describes
   desired state belongs in a template.
2. **Idempotent.** Every script must be safe to re-run. A script that only works
   once is a script that will be run twice during an incident.
3. **No secrets.** Scripts may prompt for a secret or read one from Key Vault.
   None may ever contain, log or echo one.
4. **Cross-platform pairs.** Ship `.sh` and `.ps1` together — contributors are on
   Windows, macOS and Linux, and CI is on Linux.
