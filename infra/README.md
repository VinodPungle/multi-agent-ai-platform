# Infrastructure

Infrastructure as Code for the Enterprise Multi-Agent AI Platform, using **Bicep**
and the **Azure Developer CLI (azd)**.

```
infra/
├── bicep/
│   ├── main.bicep              Subscription-scoped entry point
│   ├── main.parameters.json    azd parameter bindings
│   └── modules/                One module per resource concern
├── environments/               Per-environment parameter files (Milestone 06)
├── scripts/                    Provisioning and operational helpers
└── README.md
```

`azure.yaml` lives at the repository root, because azd looks for it there and
nowhere else.

## Status: Milestone 01 scaffold

This milestone declares the resource graph and provisions the foundation. It is
**not exercised end to end** — `azd up` is first run in Milestone 06.

Declaring the shape now means the deployment topology is reviewed alongside the
architecture rather than invented under deadline pressure later. CI validates
that every template compiles on every pull request.

| Resource | Purpose | Milestone |
| --- | --- | --- |
| Resource group | Container for everything | 01 |
| User-assigned managed identity | Workload identity for `DefaultAzureCredential` | 01 |
| Log Analytics workspace | Structured log and trace sink | 01 |
| Application Insights | OpenTelemetry backend, workspace mode | 01 |
| Key Vault | Production secret store, RBAC authorisation | 01 |
| Container Registry | Backend and frontend images, admin user disabled | 01 |
| Container Apps environment | Shared runtime for both services | 01 |
| Container Apps (backend, frontend) | Deployed by azd from `azure.yaml` | 06 |
| Azure AI Foundry project + Gemma 4 managed compute | Scale-to-zero inference | 05 |
| Cosmos DB, Redis, Azure AI Search | Persistent memory and retrieval | 08+ |

## Design decisions

**No secrets in templates or outputs.** The Application Insights connection
string is deliberately not a module output: it embeds an instrumentation key,
and deployment outputs are readable by anyone with read access to the deployment
history. Milestone 06 writes it to Key Vault.

**Managed identity everywhere.** The registry's admin user is disabled and no
Azure service is reached with an API key. Application code uses
`DefaultAzureCredential` unchanged between `az login` locally and Managed
Identity in Azure (`architecture.md` §55).

**Least-privilege roles.** The identity holds `AcrPull`, not `AcrPush`, and
`Key Vault Secrets User`, not `Key Vault Administrator`.

**Deterministic role assignment names.** Assignment names are `guid()` values
derived from scope, principal and role, so re-running a deployment updates the
existing assignment instead of failing on a duplicate.

**Names are derived, never hardcoded.** A `uniqueString` token over the
subscription, environment and location gives globally unique registry and vault
names without anyone inventing one.

**Infrastructure and application deploy independently.** The Container Apps
environment is provisioned here; the apps themselves are created and updated by
azd from `azure.yaml`. Separating them is what makes an application rollback
possible without touching infrastructure.

## Local usage

```bash
# Compile and lint the templates — what CI runs on every pull request.
bicep build infra/bicep/main.bicep --stdout > /dev/null

# Preview what a deployment would change, without applying it.
az deployment sub what-if \
  --location <region> \
  --template-file infra/bicep/main.bicep \
  --parameters environmentName=dev location=<region>
```

Provisioning (`azd up`) is covered in
[`docs/developer-setup.md`](../docs/developer-setup.md) and lands in Milestone 06.
