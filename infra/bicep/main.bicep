// =============================================================================
// Enterprise Multi-Agent AI Platform — infrastructure entry point
// =============================================================================
// Milestone 01 scaffold. It declares the resource graph and provisions the
// foundation every later milestone builds on: identity, secrets, observability,
// the container registry and the Container Apps environment.
//
// Milestone 06 completes it: the AI Foundry account and model deployment, both
// Container Apps, and the Key Vault secrets that carry deployment-time values to
// the running application without passing through a deployment output.
//
// Deliberately NOT provisioned here:
//   - Cosmos DB, Redis, Azure AI Search (Milestone 08+)
//   - Anything requiring a VNet. Public ingress with TLS is the Milestone 06
//     posture; network isolation is a Milestone 08 hardening step and changing
//     it later is a parameter, not a redesign.
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

// --- AI Foundry --------------------------------------------------------------
// Every attribute is a parameter. Nothing here names a model, which is what
// lets an environment serve a different one by changing a .bicepparam file.

@description('Provision an AI Foundry account. False reuses an existing one via aiFoundryEndpoint.')
param provisionAiFoundry bool = true

@description('Endpoint of an existing Foundry account, used when provisionAiFoundry is false.')
param aiFoundryEndpoint string = ''

@description('Model deployment name the application invokes.')
param aiFoundryDeploymentName string = 'FW-Kimi-K3'

@description('Publisher format, e.g. OpenAI, Fireworks, Meta.')
param aiFoundryModelFormat string = 'Fireworks'

@description('Model name as the catalogue lists it.')
param aiFoundryModelName string = 'FW-Kimi-K3'

@description('Model version. Pinned: "latest" changes behaviour with no deployment.')
param aiFoundryModelVersion string = '1'

@description('Deployment SKU.')
param aiFoundryDeploymentSku string = 'DataZoneStandard'

@description('Throughput capacity. Directly proportional to cost.')
@minValue(1)
param aiFoundryDeploymentCapacity int = 25

@description('Platform-wide model id this deployment serves. Appears in telemetry and cost rows.')
param platformModelId string = 'fw-kimi-k3'

// --- Application -------------------------------------------------------------

@description('Search backend: duckduckgo (keyless), tavily (keyed) or mock.')
@allowed(['duckduckgo', 'tavily', 'mock'])
param searchProvider string = 'duckduckgo'

@description('Tavily API key. Required only when searchProvider is tavily. Never stored in a parameter file.')
@secure()
param tavilyApiKey string = ''

@description('Minimum backend replicas. Zero saves money and costs a cold start on the first request.')
@minValue(0)
param backendMinReplicas int = 0

@description('Maximum backend replicas.')
@minValue(1)
param backendMaxReplicas int = 3

@description('Minimum frontend replicas.')
@minValue(0)
param frontendMinReplicas int = 0

@description('Maximum frontend replicas.')
@minValue(1)
param frontendMaxReplicas int = 3

// -----------------------------------------------------------------------------
// Conversation memory
// -----------------------------------------------------------------------------
// Off by default, and that is a cost decision rather than a default-off habit:
// a cache bills continuously whether or not anyone is chatting, so an
// environment that scales to zero should not pay for one unless it genuinely
// wants durable history.

@description('Provision Azure Cache for Redis and use it for conversation memory. When false the platform keeps history in-process, which is lost on restart and not shared between replicas.')
param provisionRedis bool = false

@description('Redis SKU tier. Basic has no replica and no SLA - see modules/redis.bicep.')
@allowed(['Basic', 'Standard', 'Premium'])
param redisSkuName string = 'Standard'

@description('Redis cache size. 0 is 250 MB, which holds a great many conversations.')
@minValue(0)
@maxValue(6)
param redisSkuCapacity int = 0

@description('How long a conversation survives without a write, refreshed on every write.')
@minValue(300)
param redisTtlSeconds int = 86400

// -----------------------------------------------------------------------------
// Knowledge base (RAG)
// -----------------------------------------------------------------------------
// Off by default. Indexing costs money proportional to the corpus, and a
// knowledge tool with no corpus would exist and always return nothing — which
// teaches a model to stop calling it.

@description('Index the documents in knowledge/ and register the knowledge-search tool.')
param enableKnowledge bool = false

@description('Provision an embedding deployment. GlobalStandard is pay-per-token with no idle cost, so this is far cheaper to leave provisioned than the chat model.')
param provisionEmbeddings bool = false

@description('Embedding model. 1536 dimensions for text-embedding-3-small.')
param embeddingModelName string = 'text-embedding-3-small'

@description('Vector length the embedding deployment emits. Must match the model: an index is built at one dimensionality and cannot accept another.')
param embeddingDimensions int = 1536

@description('Below this similarity a match counts as no match. Provider-specific: measured against text-embedding-3-small, genuine hits sit near 0.27 and an unanswerable question near 0.11, so 0.2 separates them. Meaningless for a different embedder.')
param knowledgeMinimumScore string = '0.2'

@description('What model routing optimises for among models that can serve a turn. Capability and context limits are constraints, not preferences, so this never causes a refusal. See ADR-0013.')
@allowed(['balanced', 'lowest_cost', 'largest_context', 'highest_capability'])
param routingObjective string = 'balanced'

@description('Create alert rules. Off where nobody is on call - a channel that pages during development gets muted, and it is the same channel production uses.')
param enableAlerts bool = false

@description('Email notified by alerts. Empty creates the rules with no action, which is valid while a channel is being decided.')
param alertNotificationEmail string = ''

@description('P95 chat latency, in milliseconds, that counts as degraded.')
param latencyThresholdMs int = 30000

@description('Tokens per hour above which spend is unexpected. Set from observed load, not from optimism.')
param hourlyTokenThreshold int = 500000

@description('Log level for the backend.')
@allowed(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
param logLevel string = 'INFO'

@description('Trace sampling ratio. Lower this before volume becomes the cost.')
@minValue(0)
@maxValue(1)
param traceSampleRatio int = 1

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
// Conversation memory
// -----------------------------------------------------------------------------
// Entra authentication, so nothing secret is produced here and nothing has to
// be written to the vault. The identity is granted a data access policy inside
// the module.

module redis 'modules/redis.bicep' = if (provisionRedis) {
  name: 'redis'
  scope: resourceGroup
  params: {
    name: 'redis-${resourcePrefix}-${resourceToken}'
    location: location
    tags: tags
    principalId: identity.outputs.principalId
    skuName: redisSkuName
    skuFamily: redisSkuName == 'Premium' ? 'P' : 'C'
    skuCapacity: redisSkuCapacity
  }
}

// The identity's object id doubles as the Redis username under Entra
// authentication - see agent_platform/memory/entra_credentials.py.
var memoryProvider = provisionRedis ? 'redis' : 'in-memory'
var redisUrl = provisionRedis ? redis!.outputs.url : ''

// -----------------------------------------------------------------------------
// Inference
// -----------------------------------------------------------------------------
// Provisioned by default, but an environment can point at an account someone
// else owns - a shared Foundry resource, or one created before this template
// existed - by setting provisionAiFoundry to false.

module aiFoundry 'modules/ai-foundry.bicep' = if (provisionAiFoundry) {
  name: 'ai-foundry'
  scope: resourceGroup
  params: {
    name: 'aif-${resourcePrefix}-${resourceToken}'
    location: location
    tags: tags
    principalId: identity.outputs.principalId
    deploymentName: aiFoundryDeploymentName
    modelFormat: aiFoundryModelFormat
    modelName: aiFoundryModelName
    modelVersion: aiFoundryModelVersion
    deploymentSkuName: aiFoundryDeploymentSku
    deploymentCapacity: aiFoundryDeploymentCapacity
    provisionEmbeddings: provisionEmbeddings
    embeddingModelName: embeddingModelName
  }
}

var resolvedFoundryEndpoint = provisionAiFoundry
  ? aiFoundry!.outputs.inferenceEndpoint
  : aiFoundryEndpoint

// An environment may deliberately have no inference resource - the testing one
// does, because nothing there calls a model and idle capacity is pure cost.
// The provider configuration has to follow, or the backend starts with the
// Foundry provider enabled and no endpoint, and its own configuration
// validation refuses to boot. Correctly, and only after a full deployment.
var foundryEnabled = provisionAiFoundry || !empty(aiFoundryEndpoint)

// The mock is the fallback, and the platform permits it only in development and
// testing: `enforce_environment_invariants` rejects it in staging and
// production, so a misconfigured production environment fails at startup rather
// than serving templated text to users.
var effectiveProviderId = foundryEnabled ? 'azure-foundry' : 'mock'
var effectiveModelId = foundryEnabled ? platformModelId : 'mock-echo'

// -----------------------------------------------------------------------------
// Secrets
// -----------------------------------------------------------------------------
// Written to the vault rather than emitted as outputs. A deployment output is
// readable by anyone with read access to the resource group, permanently.

module appInsightsSecret 'modules/telemetry-secret.bicep' = {
  name: 'secret-appinsights'
  scope: resourceGroup
  params: {
    applicationInsightsName: monitoring.outputs.applicationInsightsName
    keyVaultName: keyVault.outputs.name
  }
}

var hasTavilyKey = !empty(tavilyApiKey)

module tavilySecret 'modules/key-vault-secret.bicep' = if (hasTavilyKey) {
  name: 'secret-tavily'
  scope: resourceGroup
  params: {
    keyVaultName: keyVault.outputs.name
    name: 'tavily-api-key'
    value: tavilyApiKey
    contentType: 'Tavily search API key'
  }
}

// -----------------------------------------------------------------------------
// Applications
// -----------------------------------------------------------------------------
// The frontend is deployed first so the backend can be told its origin: CORS is
// an allow-list, and a wildcard is rejected in production by the platform's own
// configuration validation.

module frontendApp 'modules/container-app.bicep' = {
  name: 'frontend-app'
  scope: resourceGroup
  params: {
    name: 'ca-${resourcePrefix}-frontend-${resourceToken}'
    location: location
    // `azd-service-name` is how azd matches this app to the service in
    // azure.yaml. Without it, `azd deploy` updates nothing and reports success.
    tags: union(tags, { 'azd-service-name': 'frontend' })
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    identityId: identity.outputs.id
    containerRegistryServer: containerRegistry.outputs.loginServer
    targetPort: 8080
    readinessPath: '/healthz'
    minReplicas: frontendMinReplicas
    maxReplicas: frontendMaxReplicas
    cpu: '0.25'
    memory: '0.5Gi'
  }
}

module backendApp 'modules/container-app.bicep' = {
  name: 'backend-app'
  scope: resourceGroup
  params: {
    name: 'ca-${resourcePrefix}-backend-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'backend' })
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    identityId: identity.outputs.id
    containerRegistryServer: containerRegistry.outputs.loginServer
    targetPort: 8000
    livenessPath: '/live'
    readinessPath: '/ready'
    minReplicas: backendMinReplicas
    maxReplicas: backendMaxReplicas
    cpu: '1.0'
    memory: '2Gi'
    environmentVariables: [
      { name: 'PLATFORM_APP__ENVIRONMENT', value: deploymentEnvironment }
      { name: 'PLATFORM_APP__NAME', value: 'multi-agent-ai-platform' }
      // Debug is refused outside development by the platform's own startup
      // validation. Setting it explicitly means a mistake fails at boot rather
      // than exposing stack traces to users.
      { name: 'PLATFORM_APP__DEBUG', value: 'false' }
      { name: 'PLATFORM_SERVER__HOST', value: '0.0.0.0' }
      { name: 'PLATFORM_SERVER__PORT', value: '8000' }
      { name: 'PLATFORM_SERVER__CORS_ORIGINS', value: frontendApp.outputs.uri }
      { name: 'PLATFORM_LOGGING__LEVEL', value: logLevel }
      { name: 'PLATFORM_LOGGING__RENDERER', value: 'json' }
      { name: 'PLATFORM_TELEMETRY__ENABLED', value: 'true' }
      { name: 'PLATFORM_TELEMETRY__SAMPLE_RATIO', value: string(traceSampleRatio) }
      // The identity the app authenticates as. DefaultAzureCredential needs
      // this to pick the right one when several are attached.
      { name: 'AZURE_CLIENT_ID', value: identity.outputs.clientId }
      { name: 'PLATFORM_AZURE_FOUNDRY__ENABLED', value: string(foundryEnabled) }
      { name: 'PLATFORM_AZURE_FOUNDRY__ENDPOINT', value: resolvedFoundryEndpoint }
      { name: 'PLATFORM_AZURE_FOUNDRY__DEPLOYMENT', value: aiFoundryDeploymentName }
      { name: 'PLATFORM_AZURE_FOUNDRY__MODEL_ID', value: platformModelId }
      { name: 'PLATFORM_ROUTING__OBJECTIVE', value: routingObjective }
      // Knowledge base. The embedding provider follows the deployment: with one
      // provisioned the platform uses it, otherwise it falls back to the local
      // model, which is semantic and needs no cloud resource.
      { name: 'PLATFORM_KNOWLEDGE__ENABLED', value: string(enableKnowledge) }
      {
        name: 'PLATFORM_KNOWLEDGE__EMBEDDING_PROVIDER'
        value: provisionEmbeddings ? 'azure-foundry' : 'local'
      }
      {
        name: 'PLATFORM_KNOWLEDGE__EMBEDDING_DEPLOYMENT'
        value: provisionEmbeddings && provisionAiFoundry ? aiFoundry!.outputs.embeddingDeploymentName : ''
      }
      {
        name: 'PLATFORM_KNOWLEDGE__EMBEDDING_DIMENSIONS'
        value: string(provisionEmbeddings ? embeddingDimensions : 384)
      }
      { name: 'PLATFORM_KNOWLEDGE__MINIMUM_SCORE', value: provisionEmbeddings ? knowledgeMinimumScore : '0.0' }
      { name: 'PLATFORM_AGENT__PROVIDER_ID', value: effectiveProviderId }
      { name: 'PLATFORM_AGENT__MODEL_ID', value: effectiveModelId }
      // The mock answers with templated text. Configuration validation rejects
      // it outside development, and this makes that explicit.
      { name: 'PLATFORM_MOCK_PROVIDER__ENABLED', value: string(!foundryEnabled) }
      // Conversation memory. `redis` is durable and shared between replicas;
      // `in-memory` is per-process and loses history on every restart.
      { name: 'PLATFORM_MEMORY__PROVIDER', value: memoryProvider }
      { name: 'PLATFORM_MEMORY__REDIS_URL', value: redisUrl }
      // Entra, never an access key. The username is the identity's object id.
      { name: 'PLATFORM_MEMORY__REDIS_AUTH_MODE', value: provisionRedis ? 'entra' : 'url' }
      { name: 'PLATFORM_MEMORY__REDIS_PRINCIPAL_ID', value: identity.outputs.principalId }
      { name: 'PLATFORM_MEMORY__REDIS_TTL_SECONDS', value: string(redisTtlSeconds) }
      { name: 'PLATFORM_FEATURES__STREAMING', value: 'true' }
      { name: 'PLATFORM_FEATURES__MEMORY', value: 'true' }
      { name: 'PLATFORM_FEATURES__EVALUATION', value: 'true' }
      { name: 'PLATFORM_FEATURES__SEARCH', value: 'true' }
      { name: 'PLATFORM_SEARCH__PROVIDER', value: searchProvider }
      { name: 'PLATFORM_AGENT__TOOL_IDS', value: 'internet-search' }
    ]
    keyVaultSecrets: concat(
      [
        {
          name: 'applicationinsights-connection-string'
          keyVaultUrl: appInsightsSecret.outputs.uri
        }
      ],
      hasTavilyKey
        ? [
            {
              name: 'tavily-api-key'
              keyVaultUrl: tavilySecret!.outputs.uri
            }
          ]
        : []
    )
    secretEnvironmentVariables: concat(
      [
        {
          name: 'PLATFORM_TELEMETRY__AZURE_MONITOR_CONNECTION_STRING'
          secretRef: 'applicationinsights-connection-string'
        }
      ],
      hasTavilyKey
        ? [
            {
              name: 'PLATFORM_SEARCH__TAVILY_API_KEY'
              secretRef: 'tavily-api-key'
            }
          ]
        : []
    )
  }
}

// -----------------------------------------------------------------------------
// Alerting
// -----------------------------------------------------------------------------
// Declared after the apps because the rules reference them. Off by default:
// see `enableAlerts`.

module alerts 'modules/alerts.bicep' = if (enableAlerts) {
  name: 'alerts'
  scope: resourceGroup
  params: {
    tags: tags
    backendAppId: backendApp.outputs.id
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsResourceId
    applicationInsightsId: monitoring.outputs.applicationInsightsId
    enabled: enableAlerts
    notificationEmail: alertNotificationEmail
    latencyThresholdMs: latencyThresholdMs
    hourlyTokenThreshold: hourlyTokenThreshold
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

@description('Conversation memory backend actually in effect.')
output PLATFORM_MEMORY_PROVIDER string = memoryProvider

@description('Redis hostname, empty when no cache was provisioned. Not a secret: authentication is by Entra token, so there is no password to disclose.')
output AZURE_REDIS_HOST string = provisionRedis ? redis!.outputs.hostName : ''

@description('Public URL of the chat interface.')
output SERVICE_FRONTEND_URI string = frontendApp.outputs.uri

@description('Public URL of the API.')
output SERVICE_BACKEND_URI string = backendApp.outputs.uri

@description('Foundry inference endpoint the backend uses. A resource identifier, not a secret.')
output AZURE_AI_FOUNDRY_ENDPOINT string = resolvedFoundryEndpoint

@description('Model deployment the backend invokes.')
output AZURE_AI_FOUNDRY_DEPLOYMENT string = aiFoundryDeploymentName

@description('Whether alert rules were created for this environment.')
output ALERTS_ENABLED bool = enableAlerts

@description('Whether those alerts will actually notify anyone. False means the rules exist and fire silently.')
output ALERTS_NOTIFY bool = enableAlerts ? alerts!.outputs.notificationConfigured : false
