// =============================================================================
// Development
// =============================================================================
// Cheapest posture that is still real. Scale-to-zero everywhere, minimum
// retention, full-fidelity traces because volume is low and debugging is the
// whole point of this environment.
//
//   azd env set AZURE_ENV_NAME dev
//   az deployment sub create --location <region> \
//     --template-file infra/bicep/main.bicep \
//     --parameters infra/environments/development.bicepparam
//
// No secret appears in this file or any file beside it. `tavilyApiKey` is a
// secure parameter supplied at deploy time; see the deployment runbook.
// =============================================================================

using '../bicep/main.bicep'

param environmentName = 'dev'
param location = 'centralus'
param deploymentEnvironment = 'development'

param logRetentionDays = 30
param logLevel = 'DEBUG'
param traceSampleRatio = 1

// Scale to zero between uses. A cold start is acceptable here and the idle cost
// is not.
param backendMinReplicas = 0
param backendMaxReplicas = 2
param frontendMinReplicas = 0
param frontendMaxReplicas = 2

// Keyless, so a developer environment needs no accounts to perform a real
// search.
param searchProvider = 'duckduckgo'

param provisionAiFoundry = true
param aiFoundryDeploymentName = 'FW-Kimi-K3'
param aiFoundryModelFormat = 'Fireworks'
param aiFoundryModelName = 'FW-Kimi-K3'
param aiFoundryModelVersion = '1'
param aiFoundryDeploymentSku = 'DataZoneStandard'
param aiFoundryDeploymentCapacity = 25
param platformModelId = 'fw-kimi-k3'

// In-process memory. History is lost on restart, which on a developer
// environment that scales to zero happens constantly — and that is the right
// trade against paying for a cache nobody is using. Compose runs a real Redis
// locally for anyone who wants to exercise the durable path.
param provisionRedis = false
