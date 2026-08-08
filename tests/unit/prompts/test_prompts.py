"""Prompt loading, versioning and rendering.

Prompts are the one platform asset that fails *quietly*. A missing variable does
not raise — it reaches a model as the literal text ``{{ locale }}`` and produces
a plausible answer to a subtly wrong prompt. These tests exist to make that class
of failure loud.

The real prompt files under ``/prompts`` are covered too, because a malformed one
would otherwise stop the application at startup with no test having noticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_platform.exceptions.base import ConfigurationError, NotFoundError, ValidationError
from agent_platform.prompts.file_prompt_provider import FilePromptProvider
from agent_platform.prompts.renderer import render_prompt
from agent_platform_sdk.dto.prompt import PromptAsset, PromptVariable
from agent_platform_sdk.interfaces.prompt_provider import PromptProvider
from agent_platform_sdk.types.enums import HealthStatus

pytestmark = pytest.mark.unit

VALID = """---
prompt_id: test-prompt
version: '1.0'
description: A test prompt.
---

You are a test assistant.
"""


def write(root: Path, name: str, content: str) -> None:
    """Write a prompt file into ``root``."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestContractConformance:
    def test_it_satisfies_the_prompt_provider_contract(self, tmp_path: Path) -> None:
        assert isinstance(FilePromptProvider(tmp_path), PromptProvider)


class TestLoading:
    async def test_a_prompt_is_loaded_from_disk(self, tmp_path: Path) -> None:
        write(tmp_path, "agents/chat/system.md", VALID)
        provider = FilePromptProvider(tmp_path)

        await provider.initialize()

        asset = await provider.get("test-prompt")
        assert asset.template == "You are a test assistant."

    async def test_prompts_are_found_recursively(self, tmp_path: Path) -> None:
        write(tmp_path, "deeply/nested/path/system.md", VALID)
        provider = FilePromptProvider(tmp_path)

        await provider.initialize()

        assert await provider.get("test-prompt")

    async def test_readme_files_are_not_treated_as_prompts(self, tmp_path: Path) -> None:
        """Documentation lives alongside the assets."""
        write(tmp_path, "README.md", "# Prompts\n\nNot a prompt.")
        provider = FilePromptProvider(tmp_path)

        await provider.initialize()

        assert await provider.list_versions("anything") == ()

    async def test_a_missing_directory_is_not_a_startup_failure(self, tmp_path: Path) -> None:
        """Startup survives so the failure is diagnosable, not a crash loop."""
        provider = FilePromptProvider(tmp_path / "does-not-exist")

        await provider.initialize()

        assert await provider.list_versions("anything") == ()

    async def test_an_empty_registry_reports_unhealthy(self, tmp_path: Path) -> None:
        """Zero prompts is not healthy, however calmly it fails.

        This previously reported HEALTHY, on the reasoning that a deployment may
        legitimately carry no prompts. In practice it produced a fully green
        dashboard on a platform that could not answer a single request: every
        agent turn resolves a prompt, so a provider holding none serves nothing.

        UNHEALTHY rather than DEGRADED, per the enum's own definition — degraded
        still serves traffic. It also fails readiness, which correctly stops a
        misconfigured container from receiving any.
        """
        provider = FilePromptProvider(tmp_path / "does-not-exist")
        await provider.initialize()

        health = await provider.health_check()

        assert health.status is HealthStatus.UNHEALTHY

    async def test_the_unhealthy_detail_names_the_directory(self, tmp_path: Path) -> None:
        """The cause is nearly always a relative path and an unexpected CWD."""
        missing = tmp_path / "does-not-exist"
        provider = FilePromptProvider(missing)
        await provider.initialize()

        detail = (await provider.health_check()).detail or ""

        assert str(missing) in detail

    async def test_a_populated_registry_is_healthy(self, tmp_path: Path) -> None:
        write(tmp_path, "greet.md", VALID)
        provider = FilePromptProvider(tmp_path)
        await provider.initialize()

        assert (await provider.health_check()).status is HealthStatus.HEALTHY


class TestMalformedFiles:
    """A broken prompt must stop startup, not a user's request."""

    async def test_a_file_without_front_matter_is_refused(self, tmp_path: Path) -> None:
        write(tmp_path, "bad.md", "Just a body, no metadata.")
        provider = FilePromptProvider(tmp_path)

        with pytest.raises(ConfigurationError, match="no YAML front matter"):
            await provider.initialize()

    async def test_unterminated_front_matter_is_refused(self, tmp_path: Path) -> None:
        write(tmp_path, "bad.md", "---\nprompt_id: x\nversion: '1'\n\nBody without a closing rule")
        provider = FilePromptProvider(tmp_path)

        with pytest.raises(ConfigurationError, match="unterminated"):
            await provider.initialize()

    async def test_invalid_yaml_is_refused(self, tmp_path: Path) -> None:
        write(tmp_path, "bad.md", "---\nprompt_id: [unclosed\n---\nBody\n")
        provider = FilePromptProvider(tmp_path)

        with pytest.raises(ConfigurationError, match="invalid YAML"):
            await provider.initialize()

    async def test_missing_required_metadata_is_refused(self, tmp_path: Path) -> None:
        write(tmp_path, "bad.md", "---\ndescription: no id or version\n---\nBody\n")
        provider = FilePromptProvider(tmp_path)

        with pytest.raises(ConfigurationError, match="invalid front matter"):
            await provider.initialize()

    async def test_a_duplicated_id_and_version_is_refused(self, tmp_path: Path) -> None:
        """Anything pinned to a version must keep getting the same text."""
        write(tmp_path, "one.md", VALID)
        write(tmp_path, "two.md", VALID)
        provider = FilePromptProvider(tmp_path)

        with pytest.raises(ConfigurationError, match="declared twice"):
            await provider.initialize()


class TestVersioning:
    async def test_the_newest_version_is_served_by_default(self, tmp_path: Path) -> None:
        write(tmp_path, "v1.md", VALID)
        write(tmp_path, "v2.md", VALID.replace("'1.0'", "'2.0'").replace("test assistant", "v2"))
        provider = FilePromptProvider(tmp_path)
        await provider.initialize()

        assert (await provider.get("test-prompt")).version == "2.0"

    async def test_a_pinned_version_is_served(self, tmp_path: Path) -> None:
        """Pinning is what makes an agent's behaviour reproducible."""
        write(tmp_path, "v1.md", VALID)
        write(tmp_path, "v2.md", VALID.replace("'1.0'", "'2.0'"))
        provider = FilePromptProvider(tmp_path)
        await provider.initialize()

        assert (await provider.get("test-prompt", "1.0")).version == "1.0"

    async def test_versions_are_listed_newest_first(self, tmp_path: Path) -> None:
        """An operator must see what they can roll back to."""
        write(tmp_path, "v1.md", VALID)
        write(tmp_path, "v2.md", VALID.replace("'1.0'", "'2.0'"))
        provider = FilePromptProvider(tmp_path)
        await provider.initialize()

        assert await provider.list_versions("test-prompt") == ("2.0", "1.0")

    async def test_an_unknown_prompt_raises(self, tmp_path: Path) -> None:
        provider = FilePromptProvider(tmp_path)
        await provider.initialize()

        with pytest.raises(NotFoundError, match="No prompt registered"):
            await provider.get("nothing")

    async def test_an_unknown_version_raises_and_lists_the_known_ones(self, tmp_path: Path) -> None:
        write(tmp_path, "v1.md", VALID)
        provider = FilePromptProvider(tmp_path)
        await provider.initialize()

        with pytest.raises(NotFoundError, match=r"1\.0"):
            await provider.get("test-prompt", "9.9")


class TestRendering:
    def an_asset(self, template: str, *variables: PromptVariable) -> PromptAsset:
        return PromptAsset(prompt_id="test", version="1.0", template=template, variables=variables)

    def test_a_declared_variable_is_substituted(self) -> None:
        asset = self.an_asset("Answer in {{ locale }}.", PromptVariable(name="locale"))

        assert render_prompt(asset, {"locale": "en-GB"}) == "Answer in en-GB."

    def test_whitespace_inside_the_placeholder_is_tolerated(self) -> None:
        asset = self.an_asset("Answer in {{locale}}.", PromptVariable(name="locale"))

        assert render_prompt(asset, {"locale": "fr-FR"}) == "Answer in fr-FR."

    def test_a_missing_required_variable_is_refused(self) -> None:
        """Otherwise the literal placeholder reaches a model and looks like an answer."""
        asset = self.an_asset("Answer in {{ locale }}.", PromptVariable(name="locale"))

        with pytest.raises(ValidationError, match="locale"):
            render_prompt(asset, {})

    def test_an_optional_variable_may_be_omitted(self) -> None:
        asset = self.an_asset("Answer{{ suffix }}.", PromptVariable(name="suffix", required=False))

        assert render_prompt(asset, {}) == "Answer."

    def test_an_undeclared_placeholder_is_left_alone(self) -> None:
        """Prompts contain prose about code, and code contains braces."""
        asset = self.an_asset("Use {{ not_declared }} literally.")

        assert render_prompt(asset, {}) == "Use {{ not_declared }} literally."

    def test_a_prompt_without_variables_renders_unchanged(self) -> None:
        asset = self.an_asset("Plain text.")

        assert render_prompt(asset, {"unused": "value"}) == "Plain text."


#: The repository's real prompt assets. Resolved once, at import time: doing it
#: inside an async test is filesystem work on the event loop.
SHIPPED_PROMPTS = Path(__file__).resolve().parents[3] / "prompts"


class TestShippedPrompts:
    """The real assets must load. A malformed one stops the application."""

    async def test_every_committed_prompt_loads(self) -> None:
        provider = FilePromptProvider(SHIPPED_PROMPTS)

        await provider.initialize()

        assert await provider.get("chat-agent-system")

    async def test_the_chat_prompt_declares_the_locale_variable(self) -> None:
        """The runtime supplies `locale`; a mismatch would fail at render time."""
        provider = FilePromptProvider(SHIPPED_PROMPTS)
        await provider.initialize()

        asset = await provider.get("chat-agent-system")

        assert {variable.name for variable in asset.variables} == {"locale"}
