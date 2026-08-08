// =============================================================================
// A Container App
// =============================================================================
// One module, used for both the backend and the frontend. They differ in port,
// probes, scale and environment — all parameters — and not in shape, so a
// second near-identical module would be two places to fix the same bug.
//
// Image handling
//   `containerImage` defaults to a Microsoft sample. On the first `azd up` the
//   app is created with that placeholder, then azd builds the real image,
//   pushes it and updates the revision. Provisioning therefore never depends on
//   an image existing yet, which is what makes a from-scratch deployment work.
//
//   The `azd-service-name` tag is how azd knows which app belongs to which
//   service in azure.yaml. Without it, deployment silently updates nothing.
//
// Secrets
//   Never plain environment variables. Secrets are declared as Key Vault
//   references resolved by the managed identity at revision start, so the value
//   exists in the vault and in the running process — not in a template, a
//   parameter file, a deployment output or `az containerapp show`.
// =============================================================================

@description('Name of the Container App.')
param name string

@description('Azure region.')
param location string

@description('Tags applied to the resource. Must include azd-service-name.')
param tags object

@description('Resource id of the Container Apps environment.')
param containerAppsEnvironmentId string

@description('Resource id of the user-assigned managed identity.')
param identityId string

@description('Login server of the container registry, e.g. myregistry.azurecr.io.')
param containerRegistryServer string

@description('Container image. The default placeholder is replaced by azd on first deploy.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Port the container listens on.')
param targetPort int

@description('Whether the app is reachable from the internet.')
param external bool = true

@description('Plain (non-secret) environment variables, as name/value objects.')
param environmentVariables array = []

@description('Secrets sourced from Key Vault, as objects of { name, keyVaultUrl }.')
param keyVaultSecrets array = []

@description('Environment variables that read a declared secret, as { name, secretRef }.')
param secretEnvironmentVariables array = []

@description('HTTP path for the liveness probe. Empty disables it.')
param livenessPath string = ''

@description('HTTP path for the readiness probe. Empty disables it.')
param readinessPath string = ''

@description('Minimum replicas. Zero enables scale-to-zero, at the cost of a cold start.')
@minValue(0)
param minReplicas int = 0

@description('Maximum replicas.')
@minValue(1)
param maxReplicas int = 3

@description('CPU cores per replica. Must pair with memory in a supported combination.')
param cpu string = '0.5'

@description('Memory per replica, e.g. 1Gi. Container Apps requires a 1:2 CPU:memory ratio.')
param memory string = '1Gi'

var probes = concat(
  livenessPath == ''
    ? []
    : [
        {
          type: 'Liveness'
          httpGet: {
            path: livenessPath
            port: targetPort
          }
          // Generous: a liveness probe that fires during a slow start restarts
          // the container repeatedly and turns a slow boot into a crash loop.
          initialDelaySeconds: 15
          periodSeconds: 30
          failureThreshold: 3
        }
      ],
  readinessPath == ''
    ? []
    : [
        {
          type: 'Readiness'
          httpGet: {
            path: readinessPath
            port: targetPort
          }
          initialDelaySeconds: 5
          periodSeconds: 10
          failureThreshold: 3
        }
      ]
)

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: external
        targetPort: targetPort
        transport: 'auto'
        // TLS is terminated by the environment; this refuses the plaintext
        // port rather than redirecting, so nothing is ever sent in the clear.
        allowInsecure: false
      }
      registries: [
        {
          server: containerRegistryServer
          // Pull with the managed identity. The registry's admin user stays
          // disabled, so there is no registry password anywhere.
          identity: identityId
        }
      ]
      secrets: [
        for secret in keyVaultSecrets: {
          name: secret.name
          keyVaultUrl: secret.keyVaultUrl
          identity: identityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: name
          image: containerImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: concat(environmentVariables, secretEnvironmentVariables)
          probes: probes
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

@description('Container App resource id.')
output id string = containerApp.id

@description('Container App name.')
output name string = containerApp.name

@description('Public URL of the app.')
output uri string = 'https://${containerApp.properties.configuration.ingress.fqdn}'

@description('Fully qualified domain name, for CORS configuration.')
output fqdn string = containerApp.properties.configuration.ingress.fqdn
