// =============================================================================
// Alert rules
// =============================================================================
// What wakes someone up, and what does not.
//
// The hard part of alerting is not writing rules; it is writing few enough that
// people still read them. Every rule here answers "a human must do something
// now". Anything that is merely interesting belongs on a dashboard, where it
// can be looked at when someone chooses to look.
//
// Severities used
//   1  Users are affected right now.
//   2  Users will be affected soon, or money is being spent unexpectedly.
//   3  Worth knowing by morning.
//
// Every rule is disabled by default in non-production. A development
// environment that pages someone teaches them to ignore the channel, and the
// channel is the same one production uses.
// =============================================================================

@description('Azure region. Metric alerts are global; the location is required regardless.')
param location string = 'global'

@description('Tags applied to every rule.')
param tags object

@description('Resource id of the backend Container App.')
param backendAppId string

@description('Resource id of the Log Analytics workspace queries run against.')
param logAnalyticsWorkspaceId string

@description('Resource id of the Application Insights component.')
param applicationInsightsId string

@description('Enable the rules. False in environments where nobody is on call.')
param enabled bool = true

@description('Email address notified. Empty creates the rules with no action, which is valid while a channel is being decided.')
param notificationEmail string = ''

@description('Requests per five minutes below which the platform is considered unreachable.')
param minimumRequestRate int = 1

@description('P95 latency, in milliseconds, that counts as degraded.')
param latencyThresholdMs int = 30000

@description('Failed requests in five minutes that counts as an outage.')
param failureCountThreshold int = 5

@description('Tokens per hour above which spend is unexpected. Set from observed load, not from optimism.')
param hourlyTokenThreshold int = 500000

var hasNotificationTarget = !empty(notificationEmail)

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = if (hasNotificationTarget) {
  name: 'ag-platform-oncall'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'platform'
    enabled: true
    emailReceivers: [
      {
        name: 'oncall'
        emailAddress: notificationEmail
        // Common alert schema: without it every receiver gets a different
        // payload shape and downstream automation has to special-case each one.
        useCommonAlertSchema: true
      }
    ]
  }
}

var actions = hasNotificationTarget
  ? [
      {
        actionGroupId: actionGroup.id
      }
    ]
  : []

// -----------------------------------------------------------------------------
// Severity 1 — users are affected now
// -----------------------------------------------------------------------------

resource backendDown 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-backend-unreachable'
  location: location
  tags: tags
  properties: {
    displayName: 'Backend is not serving requests'
    description: 'No successful request in 15 minutes while the app is expected to be running. Checks the readiness probe path rather than any request, so a quiet period does not look like an outage.'
    severity: 1
    enabled: enabled
    scopes: [logAnalyticsWorkspaceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: '''
            AppRequests
            | where Url endswith "/ready"
            | where Success == true
            | summarize Successes = count()
          '''
          timeAggregation: 'Total'
          metricMeasureColumn: 'Successes'
          operator: 'LessThan'
          threshold: minimumRequestRate
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [for action in actions: action.actionGroupId]
    }
  }
}

resource highFailureRate 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-request-failures'
  location: location
  tags: tags
  properties: {
    displayName: 'Requests are failing'
    description: 'More than a handful of 5xx responses in five minutes. 4xx is excluded: a client sending bad requests is not an outage, and alerting on it trains people to ignore this rule.'
    severity: 1
    enabled: enabled
    scopes: [logAnalyticsWorkspaceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      allOf: [
        {
          query: '''
            AppRequests
            | where toint(ResultCode) >= 500
            | summarize Failures = count()
          '''
          timeAggregation: 'Total'
          metricMeasureColumn: 'Failures'
          operator: 'GreaterThan'
          threshold: failureCountThreshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [for action in actions: action.actionGroupId]
    }
  }
}

// -----------------------------------------------------------------------------
// Severity 2 — degraded, or spending unexpectedly
// -----------------------------------------------------------------------------

resource circuitOpen 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-provider-circuit-open'
  location: location
  tags: tags
  properties: {
    displayName: 'A provider circuit breaker opened'
    description: 'The gateway has stopped calling a provider after repeated failures. Users are getting fast failures rather than slow ones, which is better but still failure. Fires on the log event the breaker emits.'
    severity: 2
    enabled: enabled
    scopes: [logAnalyticsWorkspaceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: '''
            AppTraces
            | where Message has "llm.circuit_open"
            | summarize Opens = count()
          '''
          timeAggregation: 'Total'
          metricMeasureColumn: 'Opens'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [for action in actions: action.actionGroupId]
    }
  }
}

resource slowResponses 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-latency-degraded'
  location: location
  tags: tags
  properties: {
    displayName: 'Responses are slow'
    description: 'P95 request duration above the threshold over 15 minutes. P95 rather than average: an average hides the tail, and the tail is what users complain about. The window is long enough that one slow model call does not fire it.'
    severity: 2
    enabled: enabled
    scopes: [logAnalyticsWorkspaceId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: '''
            AppRequests
            | where Url has "/api/v1/chat"
            | summarize P95 = percentile(DurationMs, 95)
          '''
          timeAggregation: 'Average'
          metricMeasureColumn: 'P95'
          operator: 'GreaterThan'
          threshold: latencyThresholdMs
          failingPeriods: {
            numberOfEvaluationPeriods: 2
            minFailingPeriodsToAlert: 2
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [for action in actions: action.actionGroupId]
    }
  }
}

resource tokenSpend 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-token-spend'
  location: location
  tags: tags
  properties: {
    displayName: 'Token consumption is unusually high'
    description: 'Tokens are the platform\'s dominant variable cost, and the failure that produces them is silent: a tool loop that will not settle spends real money while every request returns 200. This is the only alert here that fires when nothing is broken.'
    severity: 2
    enabled: enabled
    scopes: [logAnalyticsWorkspaceId]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT1H'
    criteria: {
      allOf: [
        {
          query: '''
            AppTraces
            | where Message has "llm.call_completed"
            | extend Tokens = toint(Properties["completion_tokens"]) + toint(Properties["prompt_tokens"])
            | summarize TotalTokens = sum(Tokens)
          '''
          timeAggregation: 'Total'
          metricMeasureColumn: 'TotalTokens'
          operator: 'GreaterThan'
          threshold: hourlyTokenThreshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [for action in actions: action.actionGroupId]
    }
  }
}

// -----------------------------------------------------------------------------
// Severity 3 — worth knowing by morning
// -----------------------------------------------------------------------------

resource containerRestarts 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-container-restarts'
  location: 'global'
  tags: tags
  properties: {
    description: 'Replicas are restarting. One restart is normal during a deployment; a pattern of them is a crash loop, and a crash loop with a readiness probe looks like nothing from outside.'
    severity: 3
    enabled: enabled
    scopes: [backendAppId]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT1H'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'restarts'
          metricNamespace: 'Microsoft.App/containerApps'
          metricName: 'RestartCount'
          operator: 'GreaterThan'
          threshold: 3
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    autoMitigate: true
    actions: [for action in actions: {
      actionGroupId: action.actionGroupId
    }]
  }
}

@description('Ids of every rule created, so a deployment can be audited.')
output alertRuleIds array = [
  backendDown.id
  highFailureRate.id
  circuitOpen.id
  slowResponses.id
  tokenSpend.id
  containerRestarts.id
]

@description('Whether alerts will actually notify anyone.')
output notificationConfigured bool = hasNotificationTarget

@description('Application Insights component the queries read from.')
output applicationInsightsId string = applicationInsightsId
