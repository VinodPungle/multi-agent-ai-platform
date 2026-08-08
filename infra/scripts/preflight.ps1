# =============================================================================
# Pre-flight checks, run by azd before provisioning (Windows)
# =============================================================================
# The PowerShell twin of preflight.sh. Kept in step with it deliberately: a
# check that runs on one platform and not the other is a check that fails in
# whichever environment did not run it.
#
# Every check catches something that otherwise fails *slowly* — twenty minutes
# into a deployment, or after it succeeds and the application will not start.
# =============================================================================

$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Problem, [string]$Remedy)
    Write-Error "  FAILED: $Problem`n`n  Fix: $Remedy"
    exit 1
}

Write-Host 'Pre-flight checks'
Write-Host '-----------------'

# --- Signed in ---------------------------------------------------------------
try {
    $account = az account show --output json | ConvertFrom-Json
} catch {
    Fail 'Not signed in to Azure.' 'az login'
}

Write-Host "  Subscription: $($account.name) ($($account.id))"

# --- Deploying where you think you are ---------------------------------------
# The most expensive mistake available here is deploying into the wrong
# subscription, which is easy when several are configured.
if ($env:AZURE_SUBSCRIPTION_ID -and $env:AZURE_SUBSCRIPTION_ID -ne $account.id) {
    Fail "Active subscription is not the one azd is configured for ($env:AZURE_SUBSCRIPTION_ID)." `
         "az account set --subscription $env:AZURE_SUBSCRIPTION_ID"
}

# --- Resource providers ------------------------------------------------------
# An unregistered provider fails the deployment partway through, after some
# resources already exist. Registration is idempotent and takes seconds.
$providers = @(
    'Microsoft.App',
    'Microsoft.ContainerRegistry',
    'Microsoft.CognitiveServices',
    'Microsoft.KeyVault',
    'Microsoft.OperationalInsights',
    'Microsoft.Insights',
    'Microsoft.ManagedIdentity'
)

foreach ($provider in $providers) {
    try {
        $state = az provider show --namespace $provider --query registrationState -o tsv
    } catch {
        $state = 'NotFound'
    }
    if ($state -ne 'Registered') {
        Fail "Resource provider $provider is $state." "az provider register --namespace $provider --wait"
    }
}
Write-Host '  Resource providers: registered'

# --- Permission to assign roles ----------------------------------------------
# The templates create role assignments. Contributor cannot: it creates
# resources but cannot grant access to them, and the deployment fails at the
# first assignment with an authorization error that never mentions roles.
try {
    $principalId = az ad signed-in-user show --query id -o tsv
    $roles = az role assignment list --assignee $principalId --subscription $account.id `
        --query '[].roleDefinitionName' -o tsv
} catch {
    $roles = ''
}

$privileged = @('Owner', 'User Access Administrator', 'Role Based Access Control Administrator')
if ($roles -and ($privileged | Where-Object { $roles -match $_ })) {
    Write-Host '  Role assignment permission: present'
} else {
    Write-Warning '  No Owner or User Access Administrator role found.'
    Write-Warning '  The templates create role assignments; Contributor alone cannot.'
    Write-Warning '  Continuing, because the role may be inherited in a way this cannot see.'
}

# --- Tavily key, when the environment needs one ------------------------------
# Staging and production select the Tavily search provider. Without a key the
# backend refuses to start — deliberately, but better to know now.
if ($env:AZURE_ENV_NAME -in @('stg', 'prod')) {
    if (-not $env:TAVILY_API_KEY) {
        Fail 'This environment uses the Tavily search provider but TAVILY_API_KEY is not set.' `
             'azd env set TAVILY_API_KEY tvly-...  (stored in the azd environment, never committed)'
    }
    Write-Host '  Tavily key: present'
}

Write-Host '  All checks passed.'
Write-Host ''
