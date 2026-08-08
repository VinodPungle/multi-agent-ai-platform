// =============================================================================
// Azure AI Foundry account and model deployment
// =============================================================================
// The inference resource the platform's Azure provider talks to
// (architecture.md §54). Provisioned here so the model a deployment serves is
// reproducible rather than something someone once clicked.
//
// Keyless by construction
//   `disableLocalAuth` turns the account's API keys off entirely. Not "we do
//   not use them" — they cannot be used, so the class of incident where a key
//   is copied into a repository is closed at the resource rather than by
//   convention. The platform reaches this with `DefaultAzureCredential` and
//   holds no key (ADR-0011).
//
// Naming
//   `customSubDomainName` is required for token-based authentication. Without
//   it the account has no unique endpoint and Entra ID auth cannot work — the
//   failure is a 401 that says nothing about the cause.
//
// Model neutrality
//   Every attribute of the deployment is a parameter. Nothing here names a
//   model, which is what lets an environment serve Kimi, Gemma or GPT by
//   changing a `.bicepparam` file.
// =============================================================================

@description('Name of the AI Foundry (Cognitive Services) account. Globally unique.')
@minLength(2)
@maxLength(64)
param name string

@description('Azure region. Model availability varies by region.')
param location string

@description('Tags applied to the resource.')
param tags object

@description('Principal id of the managed identity that calls the model.')
param principalId string

@description('Model deployment name. This is what the application invokes.')
param deploymentName string

@description('Publisher format, e.g. OpenAI, Fireworks, Meta, Microsoft.')
param modelFormat string

@description('Model name as the catalogue lists it.')
param modelName string

@description('Model version. Pinned deliberately — "latest" changes behaviour without a deployment.')
param modelVersion string

@description('Deployment SKU, e.g. GlobalStandard, DataZoneStandard, Standard.')
param deploymentSkuName string

@description('Throughput capacity, in the SKU units. Directly proportional to cost.')
@minValue(1)
param deploymentCapacity int

@description('Content filter policy applied to the deployment.')
param raiPolicyName string = 'Microsoft.DefaultV2'

// Built-in role. Data-plane inference only — deliberately not "Cognitive
// Services Contributor", which would also permit creating and deleting
// deployments. The workload needs to call the model, not manage it.
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    // Required for Entra ID authentication. Also makes the endpoint
    // predictable, which is what the application's configuration records.
    customSubDomainName: name

    // The whole point. With local auth disabled the account has no usable API
    // key, so there is nothing to leak, rotate or accidentally commit.
    disableLocalAuth: true

    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: deploymentName
  sku: {
    name: deploymentSkuName
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: modelFormat
      name: modelName
      version: modelVersion
    }
    raiPolicyName: raiPolicyName
    // Fail an over-quota request rather than silently degrading it.
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource inferenceAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  // Deterministic, so re-running the deployment updates the assignment rather
  // than failing on a duplicate.
  name: guid(account.id, principalId, cognitiveServicesUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      cognitiveServicesUserRoleId
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Account resource id.')
output id string = account.id

@description('Account name.')
output name string = account.name

@description('Inference endpoint the platform is configured with. Not a secret — a resource identifier.')
output inferenceEndpoint string = '${account.properties.endpoint}models'

@description('Deployment name the application invokes.')
output deploymentName string = deployment.name
