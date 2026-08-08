#!/usr/bin/env sh
# =============================================================================
# Pre-flight checks, run by azd before provisioning
# =============================================================================
# Every check here catches something that otherwise fails *slowly*: twenty
# minutes into a deployment, or after it succeeds and the application cannot
# start. A failed pre-flight costs seconds; the alternative costs a rollback.
#
# Exits non-zero on the first problem, with what to do about it. `continueOnError`
# is false in azure.yaml, so azd stops here.
# =============================================================================

set -eu

fail() {
    echo "  FAILED: $1" >&2
    echo >&2
    echo "  Fix: $2" >&2
    exit 1
}

echo "Pre-flight checks"
echo "-----------------"

# --- Signed in ---------------------------------------------------------------
if ! az account show >/dev/null 2>&1; then
    fail "Not signed in to Azure." "az login"
fi

SUBSCRIPTION_NAME=$(az account show --query name -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "  Subscription: ${SUBSCRIPTION_NAME} (${SUBSCRIPTION_ID})"

# --- Deploying where you think you are ---------------------------------------
# The most expensive mistake available here is deploying into the wrong
# subscription, which is easy when several are configured and az remembers the
# last one used.
if [ -n "${AZURE_SUBSCRIPTION_ID:-}" ] && [ "${AZURE_SUBSCRIPTION_ID}" != "${SUBSCRIPTION_ID}" ]; then
    fail "Active subscription is not the one azd is configured for (${AZURE_SUBSCRIPTION_ID})." \
         "az account set --subscription ${AZURE_SUBSCRIPTION_ID}"
fi

# --- Resource providers ------------------------------------------------------
# An unregistered provider fails the deployment partway through, after some
# resources exist. Registration is idempotent and takes seconds.
for PROVIDER in Microsoft.App Microsoft.ContainerRegistry Microsoft.CognitiveServices \
                Microsoft.KeyVault Microsoft.OperationalInsights Microsoft.Insights \
                Microsoft.ManagedIdentity; do
    STATE=$(az provider show --namespace "${PROVIDER}" --query registrationState -o tsv 2>/dev/null || echo "NotFound")
    if [ "${STATE}" != "Registered" ]; then
        fail "Resource provider ${PROVIDER} is ${STATE}." \
             "az provider register --namespace ${PROVIDER} --wait"
    fi
done
echo "  Resource providers: registered"

# --- Permission to assign roles ----------------------------------------------
# The templates create role assignments. Contributor cannot: it can create
# resources but not grant access to them, and the deployment fails at the first
# assignment with an authorization error that does not mention roles.
ROLES=$(az role assignment list \
    --assignee "$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo '')" \
    --subscription "${SUBSCRIPTION_ID}" \
    --query "[].roleDefinitionName" -o tsv 2>/dev/null || echo "")

case "${ROLES}" in
    *Owner*|*"User Access Administrator"*|*"Role Based Access Control Administrator"*)
        echo "  Role assignment permission: present"
        ;;
    *)
        echo "  WARNING: no Owner or User Access Administrator role found." >&2
        echo "           The templates create role assignments; Contributor alone cannot." >&2
        echo "           Continuing, because the role may be inherited in a way this cannot see." >&2
        ;;
esac

# --- Tavily key, when the environment needs one ------------------------------
# Staging and production select the Tavily search provider. Without a key the
# backend refuses to start — deliberately, but it is better to know now.
if [ "${AZURE_ENV_NAME:-}" = "stg" ] || [ "${AZURE_ENV_NAME:-}" = "prod" ]; then
    if [ -z "${TAVILY_API_KEY:-}" ]; then
        fail "This environment uses the Tavily search provider but TAVILY_API_KEY is not set." \
             "azd env set TAVILY_API_KEY tvly-... (it is stored in the azd environment, never committed)"
    fi
    echo "  Tavily key: present"
fi

echo "  All checks passed."
echo
