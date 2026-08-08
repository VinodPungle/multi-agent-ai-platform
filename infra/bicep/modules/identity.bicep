// =============================================================================
// User-assigned managed identity
// =============================================================================
// The platform's single workload identity. Application code authenticates with
// DefaultAzureCredential in every environment: `az login` locally, this identity
// in Azure (architecture.md §55). No API key is introduced for Azure services.
//
// User-assigned rather than system-assigned so role assignments survive a
// Container App being recreated, and so backend and frontend can share one
// identity if that is ever wanted.
// =============================================================================

@description('Name of the managed identity.')
param name string

@description('Azure region.')
param location string

@description('Tags applied to the resource.')
param tags object

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

@description('Resource id, for assigning the identity to a Container App.')
output id string = managedIdentity.id

@description('Client id, passed to the app as AZURE_CLIENT_ID for DefaultAzureCredential.')
output clientId string = managedIdentity.properties.clientId

@description('Principal (object) id, used as the target of role assignments.')
output principalId string = managedIdentity.properties.principalId

@description('Identity name.')
output name string = managedIdentity.name
