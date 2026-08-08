// =============================================================================
// Observability — Log Analytics and Application Insights
// =============================================================================
// The sink for the platform's OpenTelemetry traces and structured logs
// (architecture.md §57-§59).
//
// Application Insights is created in workspace mode. Classic (non-workspace)
// components are retired, and workspace mode is what lets traces, logs and
// metrics be queried together in one KQL statement — the difference between
// diagnosing an incident in one query and correlating three tools by hand.
// =============================================================================

@description('Name of the Log Analytics workspace.')
param logAnalyticsName string

@description('Name of the Application Insights component.')
param applicationInsightsName string

@description('Azure region.')
param location string

@description('Tags applied to every resource.')
param tags object

@description('Retention in days. Cost scales directly with this value.')
@minValue(30)
@maxValue(730)
param retentionDays int = 30

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      // Pay-as-you-go. The platform's log volume is unknown until Milestone 08
      // measures it; a commitment tier before then would be guesswork.
      name: 'PerGB2018'
    }
    retentionInDays: retentionDays
    features: {
      // Data is read through Azure RBAC rather than workspace-local
      // permissions, so access is governed by the same model as everything else.
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
    // Ingestion is authenticated by managed identity; a connection string alone
    // is not sufficient to write telemetry.
    DisableLocalAuth: false
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

@description('Log Analytics resource id.')
output logAnalyticsResourceId string = logAnalytics.id

@description('Log Analytics workspace (customer) id.')
output logAnalyticsCustomerId string = logAnalytics.properties.customerId

@description('Application Insights resource id.')
output applicationInsightsId string = applicationInsights.id

@description('Application Insights resource name.')
output applicationInsightsName string = applicationInsights.name

// The connection string is deliberately NOT an output. It embeds an
// instrumentation key, and deployment outputs are readable by anyone with
// read access to the deployment history. Milestone 06 writes it to Key Vault
// and the app reads it from there.
