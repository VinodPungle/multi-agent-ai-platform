"""Environment verification behaviour.

The script is the first thing a new contributor runs, which makes a wrong answer
from it expensive: a false failure sends someone reinstalling a tool that was
fine, and a false pass hands them a confusing error from a different tool an
hour later.

Every test here injects a fake command runner, so the suite asserts the
classification logic rather than what happens to be installed on the machine
running it — which is the only way these assertions can hold in CI, in a Dev
Container and on a developer laptop at once.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from verify_environment import (
    REQUIREMENTS,
    CheckResult,
    CommandRunner,
    Status,
    ToolRequirement,
    check_tool,
    format_report,
    parse_version,
)

pytestmark = pytest.mark.unit


def a_requirement(
    *,
    name: str = "Tool",
    minimum_version: tuple[int, ...] | None = (1, 0),
    required: bool = True,
) -> ToolRequirement:
    """Build a requirement for tests that do not care about the details."""
    return ToolRequirement(
        name=name,
        executable="tool",
        version_args=("--version",),
        minimum_version=minimum_version,
        required=required,
        purpose="testing",
        install_hint="install it",
    )


def runner_returning(output: str | None) -> CommandRunner:
    """Return a command runner that always answers ``output``."""

    def run(command: Sequence[str]) -> str | None:
        del command
        return output

    return run


class TestVersionParsing:
    """Tools disagree about how to print a version. All of them get parsed."""

    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            ("git version 2.47.1", (2, 47, 1)),
            ("git version 2.47.1.windows.1", (2, 47, 1)),
            ("uv 0.5.14", (0, 5, 14)),
            ("v22.11.0", (22, 11, 0)),
            ("10.9.2", (10, 9, 2)),
            ("Docker version 27.3.1, build ce12230", (27, 3, 1)),
            ("Task version: v3.40.1", (3, 40, 1)),
            ("3", (3,)),
        ],
    )
    def test_a_version_is_extracted(self, output: str, expected: tuple[int, ...]) -> None:
        assert parse_version(output) == expected

    def test_output_without_a_version_returns_none(self) -> None:
        assert parse_version("command not found") is None

    def test_the_first_number_wins(self) -> None:
        """Every tool prints its own version before any other number."""
        assert parse_version("mytool 1.2.3 (built against libfoo 9.9)") == (1, 2, 3)


class TestClassification:
    """The four outcomes a check can produce."""

    def test_a_missing_tool_is_reported_missing(self) -> None:
        result = check_tool(a_requirement(), runner_returning(None))

        assert result.status is Status.MISSING
        assert result.found_version is None

    def test_a_recent_enough_tool_passes(self) -> None:
        result = check_tool(a_requirement(minimum_version=(1, 0)), runner_returning("tool 1.4.0"))

        assert result.status is Status.OK
        assert result.found_version == "1.4.0"

    def test_an_old_tool_is_reported_outdated(self) -> None:
        result = check_tool(a_requirement(minimum_version=(2, 0)), runner_returning("tool 1.9.9"))

        assert result.status is Status.OUTDATED

    def test_an_unreadable_version_is_not_a_failure(self) -> None:
        """An unrecognised version string is this script's problem, not the developer's."""
        result = check_tool(a_requirement(), runner_returning("some other output"))

        assert result.status is Status.UNREADABLE
        assert result.blocks_setup is False

    def test_a_requirement_without_a_minimum_accepts_any_version(self) -> None:
        result = check_tool(a_requirement(minimum_version=None), runner_returning("tool 0.0.1"))

        assert result.status is Status.OK


class TestVersionComparison:
    """Comparing a three-part version against a one-part minimum is the trap."""

    def test_a_longer_version_satisfies_a_shorter_minimum(self) -> None:
        """Node 20.11.0 satisfies a minimum of 20 — a naive tuple compare says otherwise."""
        result = check_tool(a_requirement(minimum_version=(20,)), runner_returning("v20.11.0"))

        assert result.status is Status.OK

    def test_the_exact_minimum_is_accepted(self) -> None:
        result = check_tool(a_requirement(minimum_version=(2, 40)), runner_returning("2.40.0"))

        assert result.status is Status.OK

    def test_one_patch_below_the_minimum_is_rejected(self) -> None:
        result = check_tool(a_requirement(minimum_version=(2, 40)), runner_returning("2.39.5"))

        assert result.status is Status.OUTDATED


class TestBlockingBehaviour:
    """An optional tool must never stop someone from starting work."""

    @pytest.mark.parametrize("status", [Status.MISSING, Status.OUTDATED])
    def test_a_required_tool_blocks(self, status: Status) -> None:
        result = CheckResult(a_requirement(required=True), status)

        assert result.blocks_setup is True

    @pytest.mark.parametrize("status", list(Status))
    def test_an_optional_tool_never_blocks(self, status: Status) -> None:
        result = CheckResult(a_requirement(required=False), status)

        assert result.blocks_setup is False


class TestReport:
    """The report is the whole user interface. It has to say what to do next."""

    def test_a_healthy_report_says_so(self) -> None:
        results = [CheckResult(a_requirement(), Status.OK, found_version="1.0.0")]

        assert "Ready" in format_report(results)

    def test_a_failing_report_names_the_tool_and_the_fix(self) -> None:
        results = [CheckResult(a_requirement(name="uv"), Status.MISSING)]

        report = format_report(results)

        assert "uv" in report
        assert "install it" in report
        assert "Setup cannot continue" in report

    def test_a_missing_optional_tool_is_noted_but_not_fatal(self) -> None:
        results = [
            CheckResult(a_requirement(name="Git"), Status.OK, found_version="2.47.1"),
            CheckResult(a_requirement(name="Docker", required=False), Status.MISSING),
        ]

        report = format_report(results)

        assert "Ready" in report
        assert "Docker" in report
        assert "Setup cannot continue" not in report

    def test_an_outdated_tool_reports_both_versions(self) -> None:
        results = [
            CheckResult(
                a_requirement(name="Node.js", minimum_version=(20,)), Status.OUTDATED, "18.19.0"
            )
        ]

        report = format_report(results)

        assert "18.19.0" in report
        assert "20" in report

    def test_the_report_is_ascii(self) -> None:
        """It is read in PowerShell and pasted into issues; neither survives box drawing."""
        results = [CheckResult(requirement, Status.OK, "1.0.0") for requirement in REQUIREMENTS]

        format_report(results).encode("ascii")


class TestRequirements:
    """The declared toolchain must match what the documentation promises."""

    def test_every_requirement_explains_how_to_install_it(self) -> None:
        assert all(requirement.install_hint for requirement in REQUIREMENTS)

    def test_every_requirement_explains_why_it_is_needed(self) -> None:
        assert all(requirement.purpose for requirement in REQUIREMENTS)

    def test_the_tools_the_documented_workflow_cannot_run_without_are_required(self) -> None:
        required = {requirement.executable for requirement in REQUIREMENTS if requirement.required}

        assert required == {"git", "uv", "node", "npm"}

    def test_tools_a_contributor_can_work_without_are_optional(self) -> None:
        """Docker, Task and the Azure CLI are all avoidable paths, not prerequisites."""
        optional = {
            requirement.executable for requirement in REQUIREMENTS if not requirement.required
        }

        assert optional == {"docker", "task", "az"}
