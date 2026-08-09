"""Resolving a model to the provider that serves it.

This is what stops routing being decorative. Without it, a decision to use a
model on a second provider resolves to the default provider anyway, which is
then asked for a model it has never heard of — and the failure arrives from the
provider, naming the model, with nothing pointing at the resolution step that
caused it.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_platform.exceptions.base import ConfigurationError, NotFoundError
from agent_platform.gateway.registry_resolver import RegistryBackedProviderResolver
from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider
from agent_platform.registries import KeyedRegistry, ModelRegistry
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.llm_provider_resolver import LLMProviderResolver
from agent_platform_sdk.types.enums import Capability

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


def a_provider(provider_id: str, model_id: str) -> MockLLMProvider:
    """A real provider, not a stand-in.

    `MockLLMProvider` is the platform's own development provider and already
    satisfies `LLMProvider` in full. A narrower double here would be one more
    object claiming to be a provider while implementing less than one — the
    mistake this suite has recorded three times.
    """
    return MockLLMProvider(provider_id=provider_id, model_id=model_id, chunk_delay_seconds=0.0)


def a_model(model_id: str, provider_id: str, **overrides: Any) -> ModelDescriptor:  # noqa: ANN401
    fields: dict[str, Any] = {
        "model_id": model_id,
        "provider_id": provider_id,
        "display_name": model_id,
        "capabilities": frozenset({Capability.STREAMING}),
        "max_context_tokens": 8_000,
        "max_output_tokens": 1_000,
    }
    fields.update(overrides)
    return ModelDescriptor(**fields)


def a_catalogue(*models: ModelDescriptor) -> ModelRegistry:
    registry: ModelRegistry = KeyedRegistry("model")
    for model in models:
        registry.register(model.model_id, model)
    return registry


class TestContractConformance:
    def test_it_satisfies_the_resolver_contract(self) -> None:
        resolver = RegistryBackedProviderResolver(
            providers=(a_provider("p1", "m1"),),
            models=a_catalogue(a_model("m1", "p1")),
        )

        assert isinstance(resolver, LLMProviderResolver)


class TestResolution:
    async def test_a_model_resolves_to_the_provider_that_registered_it(self) -> None:
        """The whole point: two providers, and the model decides."""
        first = a_provider("provider-a", "model-a")
        second = a_provider("provider-b", "model-b")
        resolver = RegistryBackedProviderResolver(
            providers=(first, second),
            models=a_catalogue(
                a_model("model-a", "provider-a"),
                a_model("model-b", "provider-b"),
            ),
            default_provider_id="provider-a",
        )

        resolved = await resolver.resolve("model-b", CONTEXT)

        assert resolved is second

    async def test_a_pinned_provider_wins_over_the_catalogue(self) -> None:
        """Two providers can serve one model id; only the first is in the catalogue.

        A failover pair, or one open-weight model on two hosts. The routing
        decision is what says which was actually chosen, so it has to outrank a
        catalogue entry that can only name one of them.
        """
        first = a_provider("provider-a", "shared")
        second = a_provider("provider-b", "shared")
        resolver = RegistryBackedProviderResolver(
            providers=(first, second),
            models=a_catalogue(a_model("shared", "provider-a")),
        )

        resolved = await resolver.resolve("shared", CONTEXT.derive(provider_id="provider-b"))

        assert resolved is second

    async def test_an_uncatalogued_model_falls_back_to_the_default(self) -> None:
        default = a_provider("provider-a", "model-a")
        resolver = RegistryBackedProviderResolver(
            providers=(default, a_provider("provider-b", "model-b")),
            models=a_catalogue(),
            default_provider_id="provider-a",
        )

        assert await resolver.resolve("unknown", CONTEXT) is default

    async def test_a_sole_provider_needs_no_default(self) -> None:
        """The single-provider deployment, which is most of them."""
        only = a_provider("provider-a", "model-a")
        resolver = RegistryBackedProviderResolver(providers=(only,), models=a_catalogue())

        assert await resolver.resolve("anything", CONTEXT) is only


class TestFailures:
    async def test_no_registered_provider_says_so(self) -> None:
        resolver = RegistryBackedProviderResolver(providers=(), models=a_catalogue())

        with pytest.raises(NotFoundError, match="No LLM provider is registered"):
            await resolver.resolve("m1", CONTEXT)

    async def test_an_ambiguous_resolution_refuses_rather_than_guessing(self) -> None:
        """Picking one silently would answer with a model nobody chose."""
        resolver = RegistryBackedProviderResolver(
            providers=(a_provider("provider-a", "m1"), a_provider("provider-b", "m2")),
            models=a_catalogue(),
        )

        with pytest.raises(NotFoundError, match="no default is configured"):
            await resolver.resolve("unknown", CONTEXT)

    async def test_a_catalogue_naming_a_missing_provider_says_which(self) -> None:
        """A wiring mistake, and worth saying so rather than a bare 'unknown provider'."""
        resolver = RegistryBackedProviderResolver(
            providers=(a_provider("provider-a", "m1"),),
            models=a_catalogue(a_model("orphan", "provider-gone")),
        )

        with pytest.raises(NotFoundError) as raised:
            await resolver.resolve("orphan", CONTEXT)

        assert raised.value.details["provider_id"] == "provider-gone"
        assert raised.value.details["model_id"] == "orphan"

    def test_duplicate_provider_ids_fail_at_construction(self) -> None:
        """A startup mistake, and far cheaper to find here than in a request."""
        with pytest.raises(ConfigurationError, match="Duplicate LLM provider id"):
            RegistryBackedProviderResolver(
                providers=(a_provider("same", "m1"), a_provider("same", "m2")),
                models=a_catalogue(),
            )

    def test_a_default_naming_an_unregistered_provider_fails_at_construction(self) -> None:
        with pytest.raises(ConfigurationError, match="is not registered"):
            RegistryBackedProviderResolver(
                providers=(a_provider("provider-a", "m1"),),
                models=a_catalogue(),
                default_provider_id="typo",
            )


class TestNoSilentFailover:
    async def test_it_does_not_substitute_a_provider_for_an_unknown_one(self) -> None:
        """Silent failover changes which model answered with nothing recording it."""
        resolver = RegistryBackedProviderResolver(
            providers=(a_provider("provider-a", "m1"), a_provider("provider-b", "m2")),
            models=a_catalogue(a_model("m1", "provider-a")),
            default_provider_id="provider-a",
        )

        with pytest.raises(NotFoundError):
            await resolver.resolve("m1", CONTEXT.derive(provider_id="provider-c"))


class TestProviderRealism:
    def test_the_provider_used_here_satisfies_the_full_contract(self) -> None:
        """Guards the double itself: a narrower stand-in only ever tests the stand-in.

        Three defects in this project's history were a test double implementing
        less than the protocol it stood for and the suite passing anyway.
        """
        assert isinstance(a_provider("provider-a", "m1"), LLMProvider)
