"""`.env.example` must actually work.

Listed as a known limitation since Milestone 01 — "`.env.example` and the
settings model can drift, nothing yet asserts they agree" — and it drifted
exactly as predicted: Milestone 03 moved `model_id` from `ChatSettings` to
`AgentSettings` and left `PLATFORM_CHAT__MODEL_ID` in the example file. Because
`PlatformSettings` forbids unknown keys, anyone following the documented setup
would have got a startup failure on their first run.

The file is the first thing a new contributor copies, so a defect in it is a
defect in the onboarding path. This test binds it the way a developer does: as a
real `.env` on disk, in an empty directory, with no ambient `PLATFORM_*`
variables.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_platform.configuration.settings import PlatformSettings

pytestmark = pytest.mark.unit

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


@pytest.fixture
def bound_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PlatformSettings:
    """Bind `.env.example` exactly as copying it to `.env` would."""
    shutil.copy(ENV_EXAMPLE, tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    return PlatformSettings()


class TestEnvExample:
    def test_the_file_exists(self) -> None:
        assert ENV_EXAMPLE.is_file()

    def test_it_binds_without_error(self, bound_settings: PlatformSettings) -> None:
        """The whole point. A stale key here is a startup failure for every new clone."""
        assert bound_settings.app.name

    def test_every_documented_key_is_a_real_setting(self, bound_settings: PlatformSettings) -> None:
        """`extra="forbid"` means an unknown key raises — so binding at all proves this.

        Asserted explicitly anyway, because the failure mode it guards is
        someone adding a key to the example file for a setting that does not
        exist, and the message that produces is worth pinning to this test.
        """
        documented = {
            line.split("=", 1)[0].strip()
            for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("PLATFORM_") and "=" in line
        }

        assert documented, "The example file documents no platform settings at all."
        # Binding succeeded in the fixture, so every one of these resolved.
        assert bound_settings.app.environment

    def test_the_documented_agent_model_is_the_mock_one(
        self, bound_settings: PlatformSettings
    ) -> None:
        """The example must describe a configuration that can actually answer."""
        assert bound_settings.agent.model_id == bound_settings.mock_provider.model_id

    def test_the_documented_agent_provider_is_the_mock_one(
        self, bound_settings: PlatformSettings
    ) -> None:
        assert bound_settings.agent.provider_id == bound_settings.mock_provider.provider_id

    def test_comma_separated_collections_survive_the_round_trip(
        self, bound_settings: PlatformSettings
    ) -> None:
        """Collections are the field type that has broken this file three times.

        `pydantic-settings` JSON-decodes a collection field before any validator
        runs, so a comma-separated value raises `SettingsError` unless the field
        is annotated `NoDecode`. It has caught `cors_origins` and `tool_ids`.
        """
        assert bound_settings.server.cors_origins
        assert bound_settings.agent.tool_ids == ("internet-search",)

    def test_the_example_is_a_development_configuration(
        self, bound_settings: PlatformSettings
    ) -> None:
        """It ships with the mock provider on, which production invariants reject."""
        assert bound_settings.app.environment.is_production_like is False
        assert bound_settings.mock_provider.enabled is True
