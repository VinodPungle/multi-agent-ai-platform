// =============================================================================
// Testing
// =============================================================================
// Exists to run automated tests against a real deployment. Deterministic and
// free: the mock provider answers, so a test suite cannot fail because a model
// was slow, and a run of the suite costs nothing in inference.
//
// That is also why `deploymentEnvironment` is `testing` rather than
// `development` — the platform's own configuration validation permits the mock
// provider in both, and refuses it in staging and production.
// =============================================================================

using '../bicep/main.bicep'

param environmentName = 'test'
param location = 'centralus'
param deploymentEnvironment = 'testing'

param logRetentionDays = 30
param logLevel = 'DEBUG'
param traceSampleRatio = 1

param backendMinReplicas = 0
param backendMaxReplicas = 2
param frontendMinReplicas = 0
param frontendMaxReplicas = 2

// Fabricated results, no network call: a test that depends on what the internet
// says today is a test that fails for reasons unrelated to the change.
param searchProvider = 'mock'

// No inference resource at all. Nothing in this environment calls a model, so
// provisioning one would be paying for capacity to sit idle.
param provisionAiFoundry = false
param aiFoundryEndpoint = ''

// No cache. Tests that need durable memory drive the provider directly against
// a local Redis; paying for one here would buy nothing.
param provisionRedis = false
