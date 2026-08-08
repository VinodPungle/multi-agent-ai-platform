// =============================================================================
// A single Key Vault secret
// =============================================================================
// Exists so a value generated *during* deployment — an Application Insights
// connection string, for instance — can reach the running application without
// passing through a deployment output.
//
// Why not an output
//   Deployment outputs are stored in the deployment history and readable by
//   anyone with read access to the resource group, indefinitely. A secret put
//   there is disclosed to a wider audience than the vault it was meant to
//   protect it from, and it cannot be un-disclosed by rotating the vault.
//
// The value is `@secure()`, so it appears in no log, no deployment record and
// no `az deployment show` output.
// =============================================================================

@description('Name of the vault to write into.')
param keyVaultName string

@description('Name of the secret. Referenced by Container Apps as a keyVaultUrl.')
param name string

@description('The secret value.')
@secure()
param value string

@description('Content type, recorded on the secret so an operator knows what it is.')
param contentType string = ''

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: name
  properties: {
    value: value
    contentType: contentType
    attributes: {
      enabled: true
    }
  }
}

@description('Versionless secret URI. Versionless deliberately: a Container App reference pinned to a version keeps serving the old value after a rotation.')
output uri string = '${keyVault.properties.vaultUri}secrets/${name}'

@description('Secret name.')
output name string = secret.name
