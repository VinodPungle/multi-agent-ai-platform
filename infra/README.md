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

## Status: Milestone 06 complete

The resource graph is complete and deployable with `azd up`. Deployment
procedure, secrets, environments, cost and troubleshooting:
[`docs/runbooks/deployment.md`](../docs/runbooks/deployment.md).

CI compiles every template and every environment parameter file on each pull
request.

| Resource | Purpose | Milestone |
| --- | --- | --- |
| Resource group | Container for everything | 01 |
| User-assigned managed identity | Workload identity for `DefaultAzureCredential` | 01 |
| Log Analytics workspace | Structured log and trace sink | 01 |
| Application Insights | OpenTelemetry backend, workspace mode | 01 |
| Key Vault | Production secret store, RBAC authorisation | 01 |
| Container Registry | Backend and frontend images, admin user disabled | 01 |
| Container Apps environment | Shared runtime for both services | 01 |
| Container Apps (backend, frontend) | Both services, with Key Vault secret references | 06 |
| Azure AI Foundry account + model deployment | Inference, local auth disabled | 06 |
| Cosmos DB, Redis, Azure AI Search | Persistent memory and retrieval | 08+ |

## Design decisions

**No secrets in templates or outputs.** The Application Insights connection
string is deliberately not a module output: it embeds an instrumentation key,
and deployment outputs are readable — permanently — by anyone with read access
to the resource group. `modules/telemetry-secret.bicep` reads it and writes it
straight to Key Vault, so the value never crosses a module boundary. The
Container Apps read both secrets as Key Vault references resolved by the managed
identity at revision start, so they are absent from the app's environment
definition too.

**Keys are disabled, not merely unused.** The AI Foundry account is provisioned
with `disableLocalAuth: true`. An API key cannot be used even by someone who
wants to, which closes the "key copied into a repository" incident at the
resource rather than by convention.

**Environments differ in capacity and posture, not in shape.** One template,
four typed `.bicepparam` files. Testing provisions no inference resource at all
and the template configures the mock provider to match — a deployment that
cannot call a model must not be told it can.

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
