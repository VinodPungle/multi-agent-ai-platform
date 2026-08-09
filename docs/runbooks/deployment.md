# Deployment

Provisioning and deploying the platform to Azure with the Azure Developer CLI.

Everything is Infrastructure as Code. After the initial `az login` there is no
step that involves the portal, and there is nothing to click that a redeployment
would not overwrite.

---

## 1. What gets created

One resource group per environment, containing:

| Resource | Purpose |
| --- | --- |
| User-assigned managed identity | How the app authenticates — to Foundry, Key Vault and the registry |
| Log Analytics workspace | Log and trace sink |
| Application Insights | OpenTelemetry backend, workspace mode |
| Key Vault | Secrets, RBAC-authorised |
| Container Registry | Backend and frontend images, admin user disabled |
| Container Apps environment | Shared runtime |
| Container App × 2 | Backend and frontend |
| AI Foundry account + model deployment | Inference, with local auth **disabled** |
| Azure Cache for Redis | Durable conversation memory. Only when `provisionRedis` is true |

Names are derived from a hash of subscription, environment and region, so two
environments never collide and nobody invents a name by hand.

---

## 2. Before the first deployment

```bash
az login
az account set --subscription <subscription-id>
```

You need **Owner** or **User Access Administrator** on the subscription. The
templates create role assignments, and Contributor cannot do that — it creates
resources but cannot grant access to them. The pre-flight check warns about
this before anything is provisioned.

---

## 3. Deploy

```bash
azd env new dev            # once per environment
azd env set AZURE_LOCATION centralus
azd up
```

`azd up` provisions the infrastructure, then builds, pushes and deploys both
container images. Expect **15–25 minutes** for a first run; the AI Foundry model
deployment is the slow part.

At the end it prints the frontend and backend URLs.

### Order is not incidental

Provisioning runs first so its outputs are in the environment before any image
is built. The frontend needs that: **Vite bakes the API URL into the bundle at
build time**, and a static site has no runtime configuration. `azure.yaml`
passes `SERVICE_BACKEND_URI` as a Docker build argument for exactly this reason.

Build the frontend image outside `azd` and it ships the Dockerfile default,
`http://localhost:8000` — every request from a user's browser then goes to their
own machine, and the failure looks like a CORS problem rather than a build one.

---

## 4. Secrets

Nothing secret is in a template, a parameter file or a deployment output.

**Application Insights connection string** — generated during provisioning,
written straight to Key Vault by a module that reads it and never returns it.
It is deliberately not a deployment output: those are readable, permanently, by
anyone with read access to the resource group.

**Tavily API key** — supplied at deploy time, never committed:

```bash
azd env set TAVILY_API_KEY tvly-...
```

azd stores it in `.azure/<env>/.env`, which is git-ignored. The Bicep parameter
is `@secure()`, so it appears in no log or output, and the template writes it to
Key Vault.

**Azure AI Foundry** has no key at all. The account is provisioned with
`disableLocalAuth: true`, so API keys cannot be used even by someone who wants
to. The app authenticates with its managed identity.

**Redis** has no key in the deployment either. The cache is provisioned with
Entra authentication enabled and the workload identity granted a **Data Owner**
access policy; the app connects with a token from the same credential chain
everything else uses. `AZURE_REDIS_HOST` is a deployment output precisely
because it discloses nothing.

Access keys still *exist* on the cache — classic Azure Cache for Redis has no
switch to disable them, unlike Foundry. Nothing in the platform uses them. See
[ADR-0012](../adr/0012-durable-conversation-memory.md).

Both container secrets are Key Vault *references*, resolved by the managed
identity when a revision starts. The values are never in the container's
environment definition, so `az containerapp show` does not disclose them.

---

## 5. Environments

Four, each with independent resources, configuration, secrets and monitoring:

| Environment | Model | Search | Memory | Min replicas | Retention |
| --- | --- | --- | --- | --- | --- |
| `development` | Foundry | duckduckgo (keyless) | in-process | 0 — scales to zero | 30 days |
| `testing` | **none** — mock provider | mock | in-process | 0 | 30 days |
| `staging` | Foundry | tavily | Redis (Standard C0) | 1 | 60 days |
| `production` | Foundry | tavily | Redis (Standard C1) | 1 | 90 days |

Parameters live in [`infra/environments/`](../../infra/environments/) as typed
`.bicepparam` files.

**Testing provisions no inference resource at all.** Nothing there calls a
model, so paying for idle capacity would buy nothing. The template follows
through: with no Foundry account the backend is configured for the mock
provider, which the platform permits in development and testing and refuses in
staging and production.

To deploy a specific environment's parameters directly:

```bash
az deployment sub create \
  --location centralus \
  --template-file infra/bicep/main.bicep \
  --parameters infra/environments/production.bicepparam
```

### Pointing an environment at a Foundry account it does not own

```bash
azd env set PROVISION_AI_FOUNDRY false
azd env set AZURE_AI_FOUNDRY_ENDPOINT https://<resource>.services.ai.azure.com/models
```

The identity still needs `Cognitive Services User` on that account — the
template can only grant roles on resources it creates.

---

## 6. Redeploying

`azd up` is idempotent. Role assignments use deterministic GUIDs derived from
scope, principal and role, so a rerun updates the existing assignment instead of
failing on a duplicate.

To deploy code without touching infrastructure:

```bash
azd deploy backend
azd deploy frontend
```

To change infrastructure without rebuilding images:

```bash
azd provision
```

---

## 7. Verifying a deployment

```bash
azd env get-values                      # URLs and resource names

curl "$(azd env get-value SERVICE_BACKEND_URI)/health"
curl "$(azd env get-value SERVICE_BACKEND_URI)/ready"
```

`/health` lists every component. Two are worth reading closely:

- **`file-prompts`** — reports UNHEALTHY with zero assets. A green dashboard
  over a platform that cannot answer any request is worse than a red one.
- **`azure-foundry`** — reports *configuration*, not reachability. It never
  calls the model, because a readiness probe that did would wake a scale-to-zero
  deployment on every poll and bill for it.

Connectivity is proven by the first real chat request.

---

## 8. Cost

The resources that cost money while idle:

| Resource | Idle cost |
| --- | --- |
| Container Apps | Only above the free grant; zero at `minReplicas: 0` |
| Log Analytics | Per GB ingested, then per GB retained |
| AI Foundry deployment | **Depends on SKU.** Provisioned throughput bills whether or not you call it |
| Azure Cache for Redis | **Bills continuously.** A cache has no idle state — this is why `provisionRedis` defaults to false |
| Key Vault, ACR, identity | Negligible |

Development and testing scale to zero. Production keeps one replica, because a
cold start on a user's first request is worse than the idle cost.

**Sampling is the telemetry cost lever.** At `traceSampleRatio: 1` every request
is traced, and volume becomes a real line on the bill before inference does.

To tear an environment down completely:

```bash
azd down --purge
```

`--purge` matters: Key Vault soft-delete otherwise holds the name for 7 days and
a redeployment with the same name fails.

---

## 8b. Cost visibility

`GET /api/v1/analytics/costs` reports token usage, estimated cost, failure
counts and mean latency, grouped by model, provider and agent.

Two caveats that matter before anyone builds on it:

- **It counts this process only.** Totals reset on restart and are not
  aggregated across replicas. The response says so in its `scope` field. For a
  figure covering the whole platform, query the `evaluation.recorded` events in
  Log Analytics — those survive restarts and cover every replica.
- **It has no authorisation.** Spend by model and agent is commercially
  sensitive and this endpoint is as open as the rest of the API. It is the first
  endpoint that should be protected when authorisation arrives.

Costs are estimates computed from the prices in configuration, never from an
invoice. A model with no pricing configured contributes zero, so an unpriced
deployment reads as free.

---

## 9. Troubleshooting

**`AuthorizationFailed` on a role assignment**
Contributor cannot create role assignments. You need Owner or User Access
Administrator.

**`MissingSubscriptionRegistration`**
A resource provider is not registered. The pre-flight check catches all seven in
advance; to fix manually: `az provider register --namespace Microsoft.App --wait`.

**Deployment succeeds, backend will not start**
Read the container's log stream. The most common cause is configuration the
platform validates at startup and refuses — `debug=true` in production, a
wildcard CORS origin, or the mock provider in a production-like environment. All
three are deliberate refusals.

**Frontend loads but every request fails**
Check what the bundle was built with. If the image was built outside `azd`, the
API URL is `http://localhost:8000`.

**Model deployment fails with a quota error**
`aiFoundryDeploymentCapacity` exceeds the subscription's quota for that SKU and
region. Lower it, or request a quota increase.

**`az role assignment` fails with `MissingSubscription`**
A defect in Azure CLI 2.85.0: any `az role assignment` command with `--scope`
fails this way, including a read-only `list`. `--subscription` does not help.
Use the ARM API instead — `az rest --method put --headers
"Content-Type=application/json" --body "@file.json"`. The header is required;
`az rest` does not set it on a PUT.

**A role was granted but the app still returns 401**
Restart the revision. A process that started before the role existed has cached
the failed credential, and the configuration being correct is not the same as
the process having noticed.

```bash
az containerapp revision restart -n <app> -g <rg> --revision <revision>
```

**Redis commands fail with `WRONGPASS` but the app is otherwise healthy**
Under Entra authentication the username must be the **object id of the
principal**, not the client id of the application. The two are both GUIDs on the
same identity and the error mentions neither. `PLATFORM_MEMORY__REDIS_PRINCIPAL_ID`
is set from `identity.outputs.principalId`; confirm it matches:

```bash
az identity show -n <identity> -g <rg> --query principalId -o tsv
```

**Conversations lose history intermittently under load**
Check `PLATFORM_MEMORY__PROVIDER`. If it is `in-memory` with more than one
replica, that is the expected behaviour and not a bug — each replica has its own
history and the ingress does not care which one a follow-up reaches. Set
`provisionRedis = true` for that environment.

**Key Vault name already exists**
A previous `azd down` without `--purge` left it soft-deleted:
`az keyvault purge --name <name>`.

---

## 10. What is not here yet

- **No CI/CD.** Deployment is a command someone runs. GitHub Actions arrives in
  Milestone 07.
- **No VNet.** Ingress is public with TLS. Private networking is a Milestone 08
  hardening step, and it is a parameter change rather than a redesign.
- **No blue/green.** Container Apps revisions make it possible; nothing
  orchestrates it.
- **Single region.** Multi-region is explicitly out of scope.
