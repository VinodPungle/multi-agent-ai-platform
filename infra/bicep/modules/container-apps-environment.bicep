// =============================================================================
// Azure Container Apps environment
// =============================================================================
// The shared runtime the backend and frontend Container Apps are deployed into
// (architecture.md §51-§53). Containers stay stateless; all state is
// externalised.
//
// The apps themselves are not declared here. azd creates and updates them from
// the service definitions in azure.yaml (Milestone 06), which keeps
// infrastructure provisioning and application deployment independent — a
// requirement of the handbook's release model.
// =============================================================================

@description('Name of the Container Apps environment.')
param name string

@description('Azure region.')
param location string

@description('Tags applied to the resource.')
param tags object

@description('Log Analytics workspace (customer) id, for container log shipping.')
param logAnalyticsCustomerId string

@description('Log Analytics resource id, used to read its shared key.')
param logAnalyticsResourceId string

@description('Enable zone redundancy. Requires a VNet-injected environment.')
param zoneRedundant bool = false

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        // `listKeys` at deploy time, so the key is never stored in a template
        // or a parameter file.
        sharedKey: listKeys(logAnalyticsResourceId, '2023-09-01').primarySharedKey
      }
    }
    zoneRedundant: zoneRedundant
  }
}

@description('Environment resource id, referenced by each Container App.')
output id string = containerAppsEnvironment.id

@description('Environment name.')
output name string = containerAppsEnvironment.name

@description('Default domain. Application URLs are derived from it.')
output defaultDomain string = containerAppsEnvironment.properties.defaultDomain

@description('Static outbound IP addresses, for allow-listing on downstream services.')
output staticIp string = containerAppsEnvironment.properties.staticIp
