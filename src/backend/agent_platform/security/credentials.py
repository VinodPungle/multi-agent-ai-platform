"""Azure credential resolution.

One place decides how the platform proves who it is, so that "authentication"
is a deployment property rather than something each provider invents.

`DefaultAzureCredential` is the whole mechanism, and it is chosen precisely
because the *same code* authenticates differently depending on where it runs:

============================  ===============================================
Local development             Azure CLI (`az login`) or the developer's IDE
Container Apps / AKS / VM     Managed Identity
CI                            Workload identity federation
============================  ===============================================

That is what `CLAUDE.md` requires — "Never use API keys for Azure AI Foundry
unless no supported identity mechanism exists" — and it means no secret is
stored, rotated, or leaked in a log, because there is no secret.

The async credential is used, not the sync one. A synchronous credential inside
an async provider blocks the event loop while it acquires a token, and token
acquisition is a network call that can take seconds on a cold start.
"""

from __future__ import annotations

from azure.identity.aio import DefaultAzureCredential

from agent_platform.telemetry.logging import get_logger

__all__ = ["COGNITIVE_SERVICES_SCOPE", "build_azure_credential"]

_logger = get_logger(__name__)

#: OAuth scope for Azure AI Foundry and Cognitive Services data-plane calls.
#:
#: Declared explicitly rather than left to the SDK's default. The inference SDK
#: can be pointed at either an Azure Machine Learning endpoint or a Cognitive
#: Services one, and those take different audiences — a wrong default produces a
#: 401 whose message says nothing about scopes.
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"

#: OAuth scope for the Azure Cache for Redis data plane.
#:
#: A different audience from the management plane. A token issued for
#: `https://management.azure.com/.default` authenticates every ARM call about
#: the cache and none of the commands against it, which fails as a bare
#: `WRONGPASS` with nothing pointing at the scope.
REDIS_SCOPE = "https://redis.azure.com/.default"


def build_azure_credential() -> DefaultAzureCredential:
    """Return the credential chain for this environment.

    No arguments, deliberately. Every knob `DefaultAzureCredential` exposes —
    which sources to exclude, which tenant, which client id — is read from the
    standard `AZURE_*` environment variables, and re-exposing them as platform
    settings would create a second, divergent way to configure the same thing.

    The chain is not narrowed. Excluding sources is a common "optimisation" that
    turns a working local setup into an obscure failure the first time someone
    runs it on a machine configured differently.
    """
    _logger.debug(
        "auth.credential_created",
        detail=(
            "DefaultAzureCredential: Azure CLI locally, Managed Identity in Azure. "
            "No API key is used or stored."
        ),
    )
    return DefaultAzureCredential()
