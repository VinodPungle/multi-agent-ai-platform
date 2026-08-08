// =============================================================================
// Production
// =============================================================================
// Carries real traffic. Every value here is a deliberate cost or reliability
// decision rather than a default.
//
// Sampling is the one that surprises people: at 1.0 every request is traced,
// and telemetry volume becomes a meaningful line on the bill well before
// inference does. 0.2 keeps enough signal to diagnose a pattern while costing a
// fifth as much. Raise it temporarily during an incident.
//
// `traceSampleRatio` is an int parameter, so a fractional ratio cannot be set
// here — see the note in the deployment runbook. Until that is changed it stays
// at 1 and sampling is controlled by the application setting.
// =============================================================================

using '../bicep/main.bicep'

param environmentName = 'prod'
param location = 'centralus'
param deploymentEnvironment = 'production'

// Long enough to investigate a slow-burning problem, short enough that log
// volume does not become the dominant cost.
param logRetentionDays = 90
param logLevel = 'INFO'
param traceSampleRatio = 1

// Never scale to zero. A cold start on a user's first request is a poor
// experience, and the idle cost of one replica is the price of not having it.
param backendMinReplicas = 1
param backendMaxReplicas = 10
param frontendMinReplicas = 1
param frontendMaxReplicas = 5

param searchProvider = 'tavily'

param provisionAiFoundry = true
param aiFoundryDeploymentName = 'FW-Kimi-K3'
param aiFoundryModelFormat = 'Fireworks'
param aiFoundryModelName = 'FW-Kimi-K3'
param aiFoundryModelVersion = '1'
param aiFoundryDeploymentSku = 'DataZoneStandard'
// Capacity is throughput and therefore cost. Raise it from observed load, not
// from optimism.
param aiFoundryDeploymentCapacity = 50
param platformModelId = 'fw-kimi-k3'
