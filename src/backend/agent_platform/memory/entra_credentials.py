"""Entra ID authentication for Azure Cache for Redis.

Why this exists at all
    The obvious way to reach a managed Redis is its access key: put the key in
    Key Vault, interpolate it into a URL, connect. It works, and it is what most
    templates do. It also puts a long-lived credential into a connection string
    that gets logged by accident, copied into a laptop's `.env`, and rotated
    only when someone remembers.

    ``CLAUDE.md`` is unambiguous — Managed Identity, no keys — and Azure Cache
    for Redis supports Entra ID on the data plane. So the platform uses a token,
    and the deployed cache has no secret the platform knows.

How Redis Entra authentication actually works
    `AUTH <username> <password>` where the username is the **object id of the
    principal** and the password is an access token for the Redis data-plane
    audience. That is the whole protocol. The unusual part is only that the
    password is short-lived, which is what the rest of this module deals with.

Token lifetime, and the sharp edge in it
    A token lasts on the order of an hour. redis-py authenticates when a
    connection is *established*, not continuously — so a pooled connection
    outlives the token it was authenticated with, and Azure closes it when the
    token expires. That looks like a random disconnect.

    It is handled rather than avoided: the provider is configured with retries,
    a reconnect acquires a fresh token through this class, and the operation
    proceeds. The cache below exists so that a reconnect storm does not become a
    token-request storm against Entra.

Local development is deliberately not this
    A laptop's Redis, and the one in Compose, have no authentication at all.
    Reaching for Entra there would mean either a cloud dependency to run tests
    or a second code path that only production exercises. Both are worse than a
    setting, which is what ``memory.auth_mode`` is.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from agent_platform.security.credentials import REDIS_SCOPE
from agent_platform.telemetry.logging import get_logger

if TYPE_CHECKING:
    from azure.core.credentials_async import AsyncTokenCredential

__all__ = ["EntraIdRedisCredentialProvider"]

_logger = get_logger(__name__)

#: Refresh this many seconds before a token actually expires.
#:
#: Not tuning. A token that is valid when it is read and expired when it reaches
#: the server produces an authentication failure that looks like a permissions
#: problem, and the window that causes it is exactly the network latency between
#: the two. Two minutes is far wider than that and far narrower than a token's
#: lifetime, so it costs nothing.
_REFRESH_MARGIN_SECONDS = 120.0


class EntraIdRedisCredentialProvider:
    """Supplies `(object_id, access_token)` to redis-py on every connect.

    Satisfies redis-py's ``CredentialProvider`` structurally — it inherits
    nothing, consistent with ADR-0004, and redis-py only ever calls the two
    methods below.
    """

    def __init__(
        self,
        credential: AsyncTokenCredential,
        principal_id: str,
        scope: str = REDIS_SCOPE,
    ) -> None:
        """Create the provider.

        Args:
            credential: The platform's async credential chain — Azure CLI
                locally, Managed Identity in Azure. Injected rather than
                constructed so that this class needs no knowledge of which.
            principal_id: Object id of the identity the token will be issued
                to. Redis uses it as the username, and it must be the object id
                of the *principal*, not the client id of the application. The
                two are easy to confuse and the failure is an opaque
                ``WRONGPASS``.
            scope: Data-plane audience. Defaults to the Redis one; overridable
                only so a sovereign cloud can supply its own.
        """
        self._credential = credential
        self._principal_id = principal_id
        self._scope = scope
        self._token: str | None = None
        self._expires_on: float = 0.0
        # Serialises refreshes. A pool re-establishing twenty connections after
        # a token expiry would otherwise make twenty identical token requests,
        # which is how a reconnect turns into throttling by Entra.
        self._lock = asyncio.Lock()

    def get_credentials(self) -> tuple[str, str]:
        """Not supported: acquiring a token is a network call.

        redis-py calls this only on synchronous connections. Doing the blocking
        acquisition it would require inside an async application stalls the
        event loop for the duration of an HTTP round trip to Entra, which is the
        specific thing the async credential exists to avoid.

        Raises:
            RuntimeError: always. The platform's Redis client is async.
        """
        message = (
            "EntraIdRedisCredentialProvider is async-only. The platform uses "
            "redis.asyncio; a synchronous connection would block the event loop "
            "while acquiring a token."
        )
        raise RuntimeError(message)

    async def get_credentials_async(self) -> tuple[str, str]:
        """Return the username and a currently-valid token.

        Called by redis-py on every connect, including every reconnect, which is
        what makes token rotation work without anything scheduling it.
        """
        return (self._principal_id, await self._access_token())

    async def _access_token(self) -> str:
        """Return a cached token, refreshing it when it is close to expiry."""
        loop = asyncio.get_running_loop()

        if self._token is not None and loop.time() < self._expires_on:
            return self._token

        async with self._lock:
            # Re-check: several connections can arrive here together, and the
            # one that waited for the lock usually finds the work already done.
            if self._token is not None and loop.time() < self._expires_on:
                return self._token

            token = await self._credential.get_token(self._scope)

            # `expires_on` is a wall-clock epoch; the loop clock is monotonic.
            # Converting through a remaining-seconds figure keeps the comparison
            # immune to the system clock being adjusted underneath us.
            remaining = token.expires_on - _epoch_now()
            self._token = token.token
            self._expires_on = loop.time() + max(remaining - _REFRESH_MARGIN_SECONDS, 0.0)

            _logger.debug(
                "memory.redis_token_acquired",
                # No token, and no principal id either: the id is not secret but
                # it identifies the platform's identity in every log line, and
                # it buys nothing here.
                valid_for_seconds=int(remaining),
                detail="Entra token acquired for the Redis data plane.",
            )
            return self._token


def _epoch_now() -> float:
    """Current wall-clock time as a Unix timestamp.

    A function so a test can compare against the same source the code uses,
    rather than asserting on a number it computed a different way.
    """
    return time.time()
