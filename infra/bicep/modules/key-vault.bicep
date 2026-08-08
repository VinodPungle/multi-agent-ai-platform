// =============================================================================
// Azure Key Vault
// =============================================================================
// Production secret store (architecture.md §56). Locally, secrets live in a
// git-ignored `.env`; in Azure they live here and are read through the
// platform's managed identity.
//
// No secret is created by this template. Provisioning creates the vault and
// grants access; populating it is an operational act, deliberately outside
// source control.
// =============================================================================

@description('Name of the key vault. Globally unique, maximum 24 characters.')
@maxLength(24)
param name string

@description('Azure region.')
param location string

@description('Tags applied to the resource.')
param tags object

@description('Principal id of the managed identity that reads secrets.')
param principalId string

@description('Soft-delete retention in days. Also the window for recovering a deleted vault.')
@minValue(7)
@maxValue(90)
param softDeleteRetentionDays int = 7

// Built-in role. Read access to secret *values* — deliberately not "Key Vault
// Administrator", which would also permit deletion and policy changes.
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId

    // RBAC rather than legacy access policies: it is the same authorisation
    // model as the rest of Azure, and it supports least-privilege built-in
    // roles that access policies cannot express.
    enableRbacAuthorization: true

    // Soft delete cannot be disabled on new vaults. Purge protection is left
    // off in this scaffold so a development environment can be torn down and
    // recreated with the same name; Milestone 06 enables it for production,
    // where an unrecoverable deletion is the greater risk.
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionDays
    enablePurgeProtection: null

    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource secretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  // A deterministic GUID: re-running the deployment updates the same assignment
  // instead of failing on a duplicate.
  name: guid(keyVault.id, principalId, keyVaultSecretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      keyVaultSecretsUserRoleId
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Key Vault resource id.')
output id string = keyVault.id

@description('Vault URI, used by the configuration provider to resolve secrets.')
output vaultUri string = keyVault.properties.vaultUri

@description('Key Vault name.')
output name string = keyVault.name
