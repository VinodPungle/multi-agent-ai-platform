// =============================================================================
// Staging
// =============================================================================
// Production-shaped, and treated as such. It holds production-like data and is
// reachable, so the platform's own validation applies the same restrictions it
// applies to production: debug off, no wildcard CORS, no mock provider.
//
// The difference from production is capacity and retention, not posture. A
// staging environment that is configured more loosely than production tests a
// system nobody will run.
// =============================================================================

using '../bicep/main.bicep'

param environmentName = 'stg'
param location = 'centralus'
param deploymentEnvironment = 'staging'

param logRetentionDays = 60
param logLevel = 'INFO'
param traceSampleRatio = 1

// One warm replica. Staging is where a cold start would be mistaken for a
// regression during a performance comparison.
param backendMinReplicas = 1
param backendMaxReplicas = 3
param frontendMinReplicas = 1
param frontendMaxReplicas = 3

// The same search backend as production, so results are comparable. Requires
// the Tavily key to be supplied at deploy time.
param searchProvider = 'tavily'

param provisionAiFoundry = true
param aiFoundryDeploymentName = 'FW-Kimi-K3'
param aiFoundryModelFormat = 'Fireworks'
param aiFoundryModelName = 'FW-Kimi-K3'
param aiFoundryModelVersion = '1'
param aiFoundryDeploymentSku = 'DataZoneStandard'
param aiFoundryDeploymentCapacity = 25
param platformModelId = 'fw-kimi-k3'
