// =============================================================================
// Application Insights connection string, delivered to Key Vault
// =============================================================================
// Exists to keep a promise Milestone 01 made: the connection string is not a
// module output, because it embeds an instrumentation key and deployment
// outputs are readable — permanently — by anyone with read access to the
// resource group.
//
// So the value never crosses a module boundary. This module reads it from the
// Application Insights resource and writes it straight into the vault, both
// inside one deployment scope. `main.bicep` learns the secret's *URI*, which is
// not sensitive, and nothing else.
// =============================================================================

@description('Name of the Application Insights resource to read the connection string from.')
param applicationInsightsName string

@description('Name of the vault to write it into.')
param keyVaultName string

@description('Name of the secret.')
param secretName string = 'applicationinsights-connection-string'

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: secretName
  properties: {
    value: applicationInsights.properties.ConnectionString
    contentType: 'Application Insights connection string'
    attributes: {
      enabled: true
    }
  }
}

@description('Versionless secret URI. Versionless deliberately: a reference pinned to a version keeps serving the old value after a rotation.')
output uri string = '${keyVault.properties.vaultUri}secrets/${secretName}'
