"""Entra authentication for Azure Cache for Redis.

The behaviour worth testing here is not "does it return a token" — it is what
happens around expiry and under concurrency, because that is where the cost of
getting it wrong lands: a reconnect storm turning into a token-request storm, or
a token that expires between being read and being used.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from agent_platform.memory.entra_credentials import EntraIdRedisCredentialProvider

pytestmark = pytest.mark.unit

PRINCIPAL_ID = "bd411814-0000-0000-0000-000000000000"


class FakeToken:
    """Mirrors `azure.core.credentials.AccessToken`: a value and an epoch."""

    def __init__(self, token: str, expires_on: int) -> None:
        self.token = token
        self.expires_on = expires_on


class RecordingCredential:
    """Counts acquisitions, so caching is observable rather than assumed."""

    def __init__(self, lifetime_seconds: int = 3600) -> None:
        self.calls = 0
        self.scopes: list[str] = []
        self._lifetime = lifetime_seconds

    async def get_token(self, *scopes: str, **kwargs: object) -> FakeToken:
        del kwargs
        self.calls += 1
        self.scopes.extend(scopes)
        # Epoch-based, as the real credential is.
        return FakeToken(f"token-{self.calls}", int(time.time()) + self._lifetime)


def build_provider(credential: RecordingCredential) -> EntraIdRedisCredentialProvider:
    return EntraIdRedisCredentialProvider(
        credential=credential,  # type: ignore[arg-type]
        principal_id=PRINCIPAL_ID,
    )


class TestCredentials:
    async def test_the_username_is_the_principal_id(self) -> None:
        """Redis authenticates as the object id, not the application's client id."""
        provider = build_provider(RecordingCredential())

        username, _ = await provider.get_credentials_async()

        assert username == PRINCIPAL_ID

    async def test_the_second_field_is_the_access_token(self) -> None:
        """Redis calls it a password; it is a short-lived bearer token."""
        provider = build_provider(RecordingCredential())

        _, issued = await provider.get_credentials_async()

        assert issued == "token-1"

    async def test_it_asks_for_the_redis_audience(self) -> None:
        """A management-plane token authenticates no Redis command and says so obscurely."""
        credential = RecordingCredential()
        provider = build_provider(credential)

        await provider.get_credentials_async()

        assert credential.scopes == ["https://redis.azure.com/.default"]


class TestCaching:
    async def test_a_valid_token_is_reused(self) -> None:
        """redis-py asks on every connect; a pool opens many."""
        credential = RecordingCredential()
        provider = build_provider(credential)

        for _ in range(5):
            await provider.get_credentials_async()

        assert credential.calls == 1

    async def test_concurrent_connects_acquire_one_token(self) -> None:
        """A pool re-establishing twenty connections must not make twenty requests.

        That is how a reconnect becomes throttling by Entra, and it happens
        precisely when the platform is already recovering from something.
        """
        credential = RecordingCredential()
        provider = build_provider(credential)

        await asyncio.gather(*(provider.get_credentials_async() for _ in range(20)))

        assert credential.calls == 1

    async def test_a_token_close_to_expiry_is_replaced(self) -> None:
        """The refresh margin is the point: a token valid when read must still be valid on arrival."""
        # Shorter than the 120s refresh margin, so the first token is already
        # considered stale by the time it is cached.
        credential = RecordingCredential(lifetime_seconds=60)
        provider = build_provider(credential)

        await provider.get_credentials_async()
        _, second = await provider.get_credentials_async()

        assert credential.calls == 2
        assert second == "token-2"


class TestSynchronousUse:
    def test_the_sync_path_refuses_rather_than_blocking(self) -> None:
        """Acquiring a token is an HTTP round trip; doing it synchronously stalls the loop."""
        provider = build_provider(RecordingCredential())

        with pytest.raises(RuntimeError, match="async-only"):
            provider.get_credentials()


class TestDisclosure:
    async def test_the_token_never_appears_in_logs(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """It is a bearer credential: a log line containing it is a usable credential.

        Read from captured **stdout** rather than `caplog`, because structlog
        renders there — an absence assertion against an empty `caplog.text`
        would pass whatever the code did.
        """
        provider = build_provider(RecordingCredential())

        await provider.get_credentials_async()

        assert "token-1" not in capsys.readouterr().out
