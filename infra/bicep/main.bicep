// =============================================================================
// Enterprise Multi-Agent AI Platform — infrastructure entry point
// =============================================================================
// Milestone 01 scaffold. It declares the resource graph and provisions the
// foundation every later milestone builds on: identity, secrets, observability,
// the container registry and the Container Apps environment.
//
// Deliberately NOT provisioned here:
//   - Azure AI Foundry project, managed compute and the Gemma 4 deployment
//     (Milestone 05)
//   - The Container App revisions themselves (Milestone 06, driven by azd)
//   - Cosmos DB, Redis, Azure AI Search (Milestone 08+)
//
// Every value is a parameter. No endpoint, name or location is hardcoded
// (CLAUDE.md, "Non-Negotiable Rules").
// =============================================================================

targetScope = 'subscription'

// -----------------------------------------------------------------------------
// Parameters
// -----------------------------------------------------------------------------

@minLength(1)
@maxLength(24)
@description('Environment name. azd supplies this; it seeds every resource name.')
param environmentName string

@minLength(1)
@description('Azure region for all resources.')
param location string

@allowed(['development', 'testing', 'staging', 'production'])
@description('Deployment environment. Drives the platform configuration handed to the app.')
param deploymentEnvironment string = 'development'

@description('Log Analytics retention in days. 30 is the free tier ceiling.')
@minValue(30)
@maxValue(730)
param logRetentionDays int = 30

@description('Tags applied to every resource. azd uses azd-env-name to track ownership.')
param tags object = {
  'azd-env-name': environmentName
  platform: 'multi-agent-ai-platform'
  environment: deploymentEnvironment
  managedBy: 'bicep'
}

// -----------------------------------------------------------------------------
// Naming
// -----------------------------------------------------------------------------
// A subscription- and environment-derived token keeps globally unique names
// (registry, key vault) unique without anyone inventing one by hand.

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var resourcePrefix = 'maap'

// -----------------------------------------------------------------------------
// Resource group
// -----------------------------------------------------------------------------

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${resourcePrefix}-${environmentName}'
  location: location
  tags: tags
}

// -----------------------------------------------------------------------------
// Identity
// -----------------------------------------------------------------------------
// A user-assigned identity, not system-assigned: it exists independently of any
// app, so role assignments survive a Container App being recreated and the same
// identity can be shared by several services.

module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: resourceGroup
  params: {
    name: 'id-${resourcePrefix}-${resourceToken}'
    location: location
    tags: tags
  }
}

// -----------------------------------------------------------------------------
// Observability
// -----------------------------------------------------------------------------

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: resourceGroup
  params: {
    logAnalyticsName: 'log-${resourcePrefix}-${resourceToken}'
    applicationInsightsName: 'appi-${resourcePrefix}-${resourceToken}'
    location: location
    tags: tags
    retentionDays: logRetentionDays
  }
}

// -----------------------------------------------------------------------------
// Secrets
// -----------------------------------------------------------------------------

module keyVault 'modules/key-vault.bicep' = {
  name: 'key-vault'
  scope: resourceGroup
  params: {
    // Key Vault names are globally unique and capped at 24 characters.
    name: take('kv-${resourcePrefix}-${resourceToken}', 24)
    location: location
    tags: tags
    principalId: identity.outputs.principalId
  }
}

// -----------------------------------------------------------------------------
// Container registry
// -----------------------------------------------------------------------------

module containerRegistry 'modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: resourceGroup
  params: {
    // Registry names are globally unique and must be alphanumeric only.
    name: take('cr${resourcePrefix}${resourceToken}', 50)
    location: location
    tags: tags
    principalId: identity.outputs.principalId
  }
}

// -----------------------------------------------------------------------------
// Container Apps environment
// -----------------------------------------------------------------------------

module containerAppsEnvironment 'modules/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: resourceGroup
  params: {
    name: 'cae-${resourcePrefix}-${resourceToken}'
    location: location
    tags: tags
    logAnalyticsCustomerId: monitoring.outputs.logAnalyticsCustomerId
    logAnalyticsResourceId: monitoring.outputs.logAnalyticsResourceId
  }
}

// -----------------------------------------------------------------------------
// Outputs
// -----------------------------------------------------------------------------
// Consumed by azd and by the deployment workflow. No secret is ever output —
// Application Insights is reached through its connection string, which is
// stored in Key Vault by Milestone 06 rather than emitted here.

@description('Resource group containing every platform resource.')
output AZURE_RESOURCE_GROUP string = resourceGroup.name

@description('Region the platform is deployed to.')
output AZURE_LOCATION string = location

@description('Login server of the container registry.')
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer

@description('Resource id of the Container Apps environment.')
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = containerAppsEnvironment.outputs.id

@description('Client id of the managed identity, for DefaultAzureCredential.')
output AZURE_CLIENT_ID string = identity.outputs.clientId

@description('Resource id of the managed identity.')
output AZURE_MANAGED_IDENTITY_ID string = identity.outputs.id

@description('Key Vault URI. Secrets are read through it, never emitted here.')
output AZURE_KEY_VAULT_ENDPOINT string = keyVault.outputs.vaultUri

@description('Application Insights resource name.')
output AZURE_APPLICATION_INSIGHTS_NAME string = monitoring.outputs.applicationInsightsName
