// =============================================================================
// Azure Container Registry
// =============================================================================
// Holds the backend and frontend images. Container Apps pulls from it using the
// platform's managed identity, so no registry credential is ever stored.
// =============================================================================

@description('Registry name. Globally unique, alphanumeric only.')
@minLength(5)
@maxLength(50)
param name string

@description('Azure region.')
param location string

@description('Tags applied to the resource.')
param tags object

@description('Principal id of the managed identity that pulls images.')
param principalId string

@allowed(['Basic', 'Standard', 'Premium'])
@description('Registry SKU. Premium adds geo-replication and private endpoints.')
param sku string = 'Basic'

// Built-in role. Pull only — a runtime identity has no reason to push.
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    // Admin user disabled: it is a shared static credential that cannot be
    // attributed to anyone and cannot be rotated without breaking every
    // consumer. Managed identity replaces it entirely.
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    zoneRedundancy: 'Disabled'
    policies: {
      // Retention of untagged manifests. Without this, every rebuilt tag orphans
      // its predecessor's layers and storage grows without bound.
      retentionPolicy: {
        status: sku == 'Premium' ? 'enabled' : 'disabled'
        days: 30
      }
    }
  }
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: containerRegistry
  name: guid(containerRegistry.id, principalId, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      acrPullRoleId
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Registry resource id.')
output id string = containerRegistry.id

@description('Registry login server, e.g. crmaapabc123.azurecr.io.')
output loginServer string = containerRegistry.properties.loginServer

@description('Registry name.')
output name string = containerRegistry.name
