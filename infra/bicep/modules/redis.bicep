// =============================================================================
// Azure Cache for Redis — durable conversation memory
// =============================================================================
// Until this existed, the deployed platform kept conversation history in the
// process. That is invisible on one replica and wrong on two: a user's next
// message can land on an instance that has never heard of them, and a scale-to-
// zero timeout discards the conversation entirely.
//
// Authentication is Entra ID, not an access key
//   The usual pattern is to put the primary key in Key Vault and interpolate it
//   into a connection string. It works, and it means the platform holds a
//   long-lived secret for a service that does not require one. This cache has
//   `aad-enabled` set and grants the workload identity a data access policy, so
//   the application authenticates with a token and there is no Redis secret
//   anywhere in the deployment.
//
//   Access keys are not *disabled* here, because the classic Azure Cache for
//   Redis service offers no switch to disable them — that arrived with Azure
//   Managed Redis. Nothing in this platform uses them.
//
// Why Standard rather than Basic by default
//   Basic is a single node with no replica and no SLA: Azure may restart it for
//   patching, and the cache is simply gone until it returns. For conversation
//   history that means every active conversation losing its context at a moment
//   nobody chose. Standard is a replicated pair. The SKU is a parameter, and
//   development sets it to Basic deliberately.
// =============================================================================

@description('Name of the cache. Must be globally unique.')
param name string

@description('Azure region.')
param location string

@description('Tags applied to the resource.')
param tags object

@description('Object id of the identity that will read and write conversations.')
param principalId string

@description('SKU family: C for Basic/Standard, P for Premium.')
@allowed(['C', 'P'])
param skuFamily string = 'C'

@description('SKU tier. Basic has no replica and no SLA; see the note above.')
@allowed(['Basic', 'Standard', 'Premium'])
param skuName string = 'Standard'

@description('Cache size. 0 is 250 MB, 1 is 1 GB. Conversation history is small; this is not the dimension that runs out first.')
@minValue(0)
@maxValue(6)
param skuCapacity int = 0

@description('Allow connections from the public internet. Container Apps reaches the cache this way until the platform has a VNet.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Enabled'

resource cache 'Microsoft.Cache/redis@2024-11-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      family: skuFamily
      name: skuName
      capacity: skuCapacity
    }
    // Unencrypted traffic is refused outright rather than merely discouraged.
    // A client that gets this wrong should fail to connect, not quietly send
    // conversation content in the clear.
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: publicNetworkAccess
    redisConfiguration: {
      // Entra authentication. Without this the access policy assignment below
      // is accepted and then does nothing, which is the worst of both.
      'aad-enabled': 'True'
      // Evict the least recently used key when memory runs out, rather than
      // refusing writes. Conversations already carry a TTL, so eviction only
      // ever happens under genuine pressure — and losing the oldest history is
      // a far better failure than a write error in the middle of a chat turn.
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}

// The data-plane grant. `redisDataOwner` is one of three built-in policies
// (Reader, Contributor, Owner); the platform needs DEL and SCAN for
// conversation deletion and clearing, which Contributor does not cover.
resource accessPolicyAssignment 'Microsoft.Cache/redis/accessPolicyAssignments@2024-11-01' = {
  parent: cache
  // Deterministic, so redeploying updates the assignment rather than failing on
  // a duplicate — the same reason role assignments use a derived GUID.
  name: guid(cache.id, principalId, 'redisDataOwner')
  properties: {
    accessPolicyName: 'Data Owner'
    objectId: principalId
    // Required by the API and used only for display. The object id above is
    // what actually grants access.
    objectIdAlias: 'platform-workload-identity'
  }
}

@description('Resource id.')
output id string = cache.id

@description('Cache name.')
output name string = cache.name

@description('Hostname. Combined with the port into a rediss:// URL by the caller — no password, because there is no password.')
output hostName string = cache.properties.hostName

@description('TLS port.')
output sslPort int = cache.properties.sslPort

@description('Connection URL with no credentials in it. Safe as an output precisely because Entra authentication leaves nothing secret to leak.')
output url string = 'rediss://${cache.properties.hostName}:${cache.properties.sslPort}'

@description('Name of the access policy assignment, so an operator can find the grant.')
output accessPolicyAssignmentName string = accessPolicyAssignment.name
