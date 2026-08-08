# Azure AI Foundry setup

How to point the platform at an Azure AI Foundry deployment, locally and in
Azure. No API key is involved at any step — that is deliberate, and it is why
there is nothing here to rotate or leak.

---

## 1. What you need

| | |
| --- | --- |
| Azure subscription | with an AI Foundry resource |
| A model deployment | the **deployment name**, which is often not the model name |
| Azure CLI 2.60+ | for local authentication |
| An RBAC role | `Cognitive Services User` on the Foundry resource |

The RBAC role is the step people miss. Owner on the subscription does **not**
imply data-plane access to the resource: you can create the deployment and still
get a 401 calling it.

```bash
az role assignment create \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Cognitive Services User" \
  --scope "$(az cognitiveservices account show -n <resource> -g <rg> --query id -o tsv)"
```

---

## 2. Find the endpoint and deployment

```bash
# The inference endpoint — use the "Azure AI Model Inference API" one,
# with /models appended.
az cognitiveservices account show -n <resource> -g <rg> \
  --query "properties.endpoints" -o json

# What is actually deployed, and under what name.
az cognitiveservices account deployment list -n <resource> -g <rg> \
  --query "[].{deployment:name,model:properties.model.name}" -o table
```

The endpoint the platform wants looks like:

```
https://<resource>.services.ai.azure.com/models
```

**`deployment` is the deployment name, not the model name.** They are frequently
different, and a mismatch produces a 404 whose message does not say so — which is
why the provider's error message says it for you.

---

## 3. Configure

```dotenv
PLATFORM_AZURE_FOUNDRY__ENABLED=true
PLATFORM_AZURE_FOUNDRY__ENDPOINT=https://<resource>.services.ai.azure.com/models
PLATFORM_AZURE_FOUNDRY__DEPLOYMENT=<deployment-name>
PLATFORM_AZURE_FOUNDRY__MODEL_ID=gemma-4

# Point the agent at it, and turn the mock off.
PLATFORM_AGENT__PROVIDER_ID=azure-foundry
PLATFORM_AGENT__MODEL_ID=gemma-4
PLATFORM_MOCK_PROVIDER__ENABLED=false
```

Configuration is validated at startup: enabling the provider without an endpoint
or deployment stops the process with a message naming the missing field, rather
than failing every chat request later.

### Reasoning models need a different token parameter

```dotenv
PLATFORM_AZURE_FOUNDRY__OUTPUT_TOKEN_PARAMETER=max_completion_tokens
```

Reasoning models reject `max_tokens` outright with an HTTP 400. This was found by
a live call, not by reading documentation — if you see a 400 on a request that
sets an output cap, this is the first thing to change.

### Pricing

```dotenv
PLATFORM_AZURE_FOUNDRY__INPUT_COST_PER_MILLION_TOKENS=0.15
PLATFORM_AZURE_FOUNDRY__OUTPUT_COST_PER_MILLION_TOKENS=0.60
```

The inference API does not report spend, so cost is computed from these. They
default to zero, which reports zero cost rather than a fabricated number that
would reach a dashboard looking real. Set them from your own published rates.

---

## 4. Authenticate

### Locally

```bash
az login
az account set --subscription <subscription-id>
```

That is all. `DefaultAzureCredential` finds the CLI session.

### In Azure

Assign a Managed Identity to the Container App and give it the same
`Cognitive Services User` role on the Foundry resource. **The application code is
identical** — no configuration switch, no separate code path. That is the whole
reason `DefaultAzureCredential` is used rather than a key.

---

## 5. Scale-to-zero

A Managed Compute deployment that has scaled to zero takes **tens of seconds** to
answer its first request while an instance starts.

- `PLATFORM_AZURE_FOUNDRY__COLD_START_TIMEOUT_SECONDS` defaults to 120.
- The provider's health check does **not** call the model, deliberately: a
  readiness probe that did would wake the deployment on every poll and bill for
  it, turning a cost-saving feature into a cost.
- `initialize()` does not call it either, for the same reason — a rolling restart
  would otherwise wake it every time.

Connectivity is proven by the first real request. If that is not acceptable for
your operations, add an explicit warm-up endpoint rather than making readiness
do it.

---

## 6. Troubleshooting

**401 / `ClientAuthenticationError`**
`az login` locally; check the Managed Identity's role assignment in Azure.
Subscription Owner does not grant data-plane access.

**404 on a deployment you can see in the portal**
You are almost certainly using the model name. Use the *deployment* name.

**HTTP 400 with an output token cap set**
Set `OUTPUT_TOKEN_PARAMETER=max_completion_tokens`.

**The first request after idle takes 30+ seconds, then works**
Working as designed. That is scale-to-zero.

**Empty content with `finish_reason: TOKEN_LIMIT_REACHED`**
A reasoning model spent the whole budget thinking. Raise the output cap.

---

## 7. Cost

Every call is billed. The platform records `prompt_tokens`, `completion_tokens`
and an estimated cost on each response and in telemetry, so spend is attributable
per agent, model and conversation before it appears on an invoice.

Set the agent's budget to bound a single turn:

```dotenv
PLATFORM_AGENT__MAX_MODEL_CALLS=4
PLATFORM_AGENT__MAX_TOOL_INVOCATIONS=4
```
