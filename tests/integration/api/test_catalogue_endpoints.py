"""Discovery endpoints for agents, tools and models.

These report what the registries *hold*, which is a different thing from what
configuration asked for — and the more useful one. A tool switched off by a
feature flag is absent here, and its absence is the answer to "why is the agent
not searching?".

The tests that matter are therefore the negative ones: a disabled capability
must not appear, and no endpoint may leak an endpoint URL or deployment name.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.api.app import create_app
from agent_platform.configuration.settings import (
    AgentSettings,
    AppSettings,
    AzureFoundrySettings,
    ChatSettings,
    Environment,
    FeatureFlagSettings,
    LoggingSettings,
    MockProviderSettings,
    PlatformSettings,
    TelemetrySettings,
)

pytestmark = pytest.mark.integration

PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts"


def build_settings(**overrides: object) -> PlatformSettings:
    fields: dict[str, object] = {
        "app": AppSettings(
            name="test-platform",
            version="0.0.0-test",
            environment=Environment.TESTING,
            debug=True,
        ),
        "logging": LoggingSettings(level="WARNING", renderer="json"),
        "telemetry": TelemetrySettings(enabled=False),
        "mock_provider": MockProviderSettings(enabled=True, chunk_delay_seconds=0.0),
        "agent": AgentSettings(provider_id="mock", model_id="mock-echo"),
        "chat": ChatSettings(agent_id="chat-agent", prompts_directory=str(PROMPTS_ROOT)),
    }
    fields.update(overrides)
    return PlatformSettings(**fields)  # type: ignore[arg-type]


def client_for(settings: PlatformSettings) -> Iterator[TestClient]:
    app: FastAPI = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def catalogue_client() -> Iterator[TestClient]:
    yield from client_for(build_settings())


class TestAgents:
    def test_it_lists_the_registered_agents(self, catalogue_client: TestClient) -> None:
        response = catalogue_client.get("/api/v1/agents")

        assert response.status_code == 200
        assert [a["agent_id"] for a in response.json()] == ["chat-agent"]

    def test_an_agent_reports_the_model_it_prefers(self, catalogue_client: TestClient) -> None:
        """A preference: routing may choose another, and the response says which."""
        (agent,) = catalogue_client.get("/api/v1/agents").json()

        assert agent["model_id"] == "mock-echo"
        assert agent["provider_id"] == "mock"

    def test_an_agent_reports_the_tools_it_declares(self, catalogue_client: TestClient) -> None:
        """What the agent asks for — not what the runtime can actually give it."""
        (agent,) = catalogue_client.get("/api/v1/agents").json()

        assert agent["tool_ids"] == ["internet-search"]

    def test_a_declared_tool_can_be_absent_from_the_tool_registry(self) -> None:
        """The pair of endpoints exists to make exactly this diagnosable.

        With search disabled the agent still *declares* internet-search, and the
        registry does not hold it. Neither view alone explains why the agent
        stopped searching; together they say so immediately.
        """
        settings = build_settings(features=FeatureFlagSettings(search=False))

        for client in client_for(settings):
            (agent,) = client.get("/api/v1/agents").json()
            registered = [t["tool_id"] for t in client.get("/api/v1/tools").json()]

            assert "internet-search" in agent["tool_ids"]
            assert "internet-search" not in registered

    def test_no_prompt_file_location_is_exposed(self, catalogue_client: TestClient) -> None:
        """A path on disk helps an operator not at all and an attacker a little."""
        body = catalogue_client.get("/api/v1/agents").text

        assert "prompts/" not in body
        assert "prompt_id" not in body


class TestTools:
    def test_a_disabled_tool_is_absent_rather_than_listed(self) -> None:
        """The absence is the answer to "why is the agent not searching?"."""
        settings = build_settings(features=FeatureFlagSettings(search=False))

        for client in client_for(settings):
            tool_ids = [t["tool_id"] for t in client.get("/api/v1/tools").json()]

            assert "internet-search" not in tool_ids

    def test_an_enabled_tool_is_listed_with_its_parameters(self) -> None:
        settings = build_settings(features=FeatureFlagSettings(search=True))

        for client in client_for(settings):
            tools = {t["tool_id"]: t for t in client.get("/api/v1/tools").json()}

            assert "internet-search" in tools
            assert "query" in tools["internet-search"]["parameters"]
            assert tools["internet-search"]["required_parameters"] == ["query"]

    def test_the_description_sent_to_models_is_shown_verbatim(self) -> None:
        """It is prompt material, and seeing it is how a bad one gets noticed."""
        settings = build_settings(features=FeatureFlagSettings(search=True))

        for client in client_for(settings):
            tools = {t["tool_id"]: t for t in client.get("/api/v1/tools").json()}

            assert "Search the internet" in tools["internet-search"]["description"]


class TestModels:
    def test_it_lists_the_catalogue(self, catalogue_client: TestClient) -> None:
        models = catalogue_client.get("/api/v1/models").json()

        assert [m["model_id"] for m in models] == ["mock-echo"]

    def test_a_model_reports_its_limits_and_capabilities(
        self,
        catalogue_client: TestClient,
    ) -> None:
        (model,) = catalogue_client.get("/api/v1/models").json()

        assert model["max_context_tokens"] > 0
        assert "streaming" in model["capabilities"]

    def test_prices_are_strings_so_decimals_survive_the_wire(
        self,
        catalogue_client: TestClient,
    ) -> None:
        """Parsing into a float would reintroduce the drift Decimal exists to avoid."""
        (model,) = catalogue_client.get("/api/v1/models").json()

        assert isinstance(model["input_cost_per_million_tokens"], str)

    def test_no_endpoint_or_deployment_name_is_exposed(self) -> None:
        """Infrastructure detail: it enumerates well and helps an operator not at all."""
        settings = build_settings(
            azure_foundry=AzureFoundrySettings(
                enabled=True,
                endpoint="https://secret-resource.services.ai.azure.com/models",
                deployment="internal-deployment-name",
                model_id="fw-kimi-k3",
            ),
            app=AppSettings(
                name="test-platform",
                version="0.0.0-test",
                environment=Environment.TESTING,
                debug=True,
            ),
        )

        for client in client_for(settings):
            body = client.get("/api/v1/models").text

            assert "secret-resource" not in body
            assert "internal-deployment-name" not in body
