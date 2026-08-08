"""Verify that the local toolchain can build and run the platform.

Run before anything else on a new machine:

    uv run --no-project python scripts/verify_environment.py

Why this exists
    Every failure it reports is one that otherwise surfaces much later, as a
    confusing error from a tool that is not the one at fault — a Node 18 that
    breaks Vite with a syntax error inside a dependency, a Python 3.11 that
    fails on ``asyncio.timeout`` usage, a missing ``uv`` that turns every
    documented command into "command not found". Naming the cause up front is
    worth the fifty lines.

Design constraints
    *Standard library only, and no imports from the platform.* This runs before
    ``uv sync`` has created an environment, so it cannot depend on anything the
    project installs — including the project itself.

    *Never a hard failure on an optional tool.* Docker and the Azure CLI are not
    needed to run the test suite, and a report that fails without them would
    train developers to ignore it.

The module is deliberately structured around an injected command runner so the
classification logic is testable without the tools being present. See
``tests/unit/scripts/test_verify_environment.py``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "REQUIREMENTS",
    "CheckResult",
    "CommandRunner",
    "Status",
    "ToolRequirement",
    "check_tool",
    "format_report",
    "main",
    "parse_version",
]

#: Extracts the first dotted number sequence from a tool's version output.
#: Tools are wildly inconsistent — ``uv 0.5.14``, ``v22.11.0``,
#: ``Docker version 27.3.1, build ce12230`` — but all of them put the version
#: first among the numbers, and none of them omit it.
_VERSION_PATTERN = re.compile(r"(\d+(?:\.\d+)*)")

#: How long to wait for a tool to print its version. A tool that cannot answer
#: in this time is broken in a way this script should report rather than hang on.
_VERSION_TIMEOUT_SECONDS = 15


class Status(StrEnum):
    """Outcome of checking one tool."""

    OK = "ok"
    OUTDATED = "outdated"
    MISSING = "missing"
    UNREADABLE = "unreadable"

    @property
    def symbol(self) -> str:
        """Return the marker shown in the report."""
        return {
            Status.OK: "OK  ",
            Status.OUTDATED: "OLD ",
            Status.MISSING: "MISS",
            Status.UNREADABLE: "??  ",
        }[self]


@dataclass(frozen=True)
class ToolRequirement:
    """A tool the platform expects to find, and what happens if it is absent."""

    name: str
    executable: str
    version_args: tuple[str, ...]
    minimum_version: tuple[int, ...] | None
    required: bool
    purpose: str
    install_hint: str


@dataclass(frozen=True)
class CheckResult:
    """The outcome of checking one requirement."""

    requirement: ToolRequirement
    status: Status
    found_version: str | None = None

    @property
    def blocks_setup(self) -> bool:
        """Whether this result should fail the verification.

        An optional tool never blocks. A required tool blocks when it is absent
        or too old, but not when its version merely could not be parsed — an
        unrecognised version string is this script's problem, not the
        developer's, and refusing to proceed over it would be obstructive.
        """
        if not self.requirement.required:
            return False
        return self.status in {Status.MISSING, Status.OUTDATED}


#: The toolchain, in the order a developer needs it.
REQUIREMENTS: tuple[ToolRequirement, ...] = (
    ToolRequirement(
        name="Git",
        executable="git",
        version_args=("--version",),
        minimum_version=(2, 40),
        required=True,
        purpose="Version control, and the hooks pre-commit installs",
        install_hint="https://git-scm.com/downloads",
    ),
    ToolRequirement(
        name="uv",
        executable="uv",
        version_args=("--version",),
        minimum_version=(0, 5),
        required=True,
        purpose="Python dependency management. Installs Python 3.12 itself.",
        install_hint=(
            "macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "        Windows: powershell -ExecutionPolicy ByPass "
            '-c "irm https://astral.sh/uv/install.ps1 | iex"'
        ),
    ),
    ToolRequirement(
        name="Node.js",
        executable="node",
        version_args=("--version",),
        # 20 is the oldest LTS the frontend toolchain supports; Vite 6 and
        # Vitest 4 both require it.
        minimum_version=(20,),
        required=True,
        purpose="Frontend build and test tooling",
        install_hint="https://nodejs.org — install the current LTS",
    ),
    ToolRequirement(
        name="npm",
        executable="npm",
        version_args=("--version",),
        minimum_version=(10,),
        required=True,
        purpose="Frontend dependency management",
        install_hint="Ships with Node.js",
    ),
    ToolRequirement(
        name="Docker",
        executable="docker",
        version_args=("--version",),
        minimum_version=(24,),
        required=False,
        purpose="`task up` and the container builds CI runs",
        install_hint="https://www.docker.com/products/docker-desktop",
    ),
    ToolRequirement(
        name="Task",
        executable="task",
        version_args=("--version",),
        minimum_version=(3,),
        required=False,
        purpose="Task runner for every documented command",
        install_hint=(
            "winget install Task.Task | brew install go-task/tap/go-task | "
            "sudo snap install task --classic"
        ),
    ),
    ToolRequirement(
        name="Azure CLI",
        executable="az",
        version_args=("version",),
        minimum_version=(2, 60),
        required=False,
        purpose="`az login` for DefaultAzureCredential. Needed from Milestone 05.",
        install_hint="https://learn.microsoft.com/cli/azure/install-azure-cli",
    ),
)

#: Runs a command and returns its combined output, or None if it cannot be run.
CommandRunner = Callable[[Sequence[str]], str | None]


def parse_version(text: str) -> tuple[int, ...] | None:
    """Extract a version tuple from a tool's version output.

    Args:
        text: Whatever the tool printed.

    Returns:
        The first dotted number sequence as a tuple, or ``None`` when the output
        contains no recognisable version.

    Examples:
        >>> parse_version("git version 2.47.1.windows.1")
        (2, 47, 1)
        >>> parse_version("v22.11.0")
        (22, 11, 0)
        >>> parse_version("no version here")
    """
    match = _VERSION_PATTERN.search(text)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def run_command(command: Sequence[str]) -> str | None:
    """Run ``command`` and return its output, or ``None`` if it cannot be run.

    Resolves the executable through :func:`shutil.which` first so that a missing
    tool is reported as missing rather than raising, and so that Windows finds
    ``npm.cmd`` when the requirement names ``npm``.
    """
    executable = shutil.which(command[0])
    if executable is None:
        return None

    try:
        completed = subprocess.run(  # noqa: S603 - fixed argument lists, resolved executable
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    # Some tools print their version to stderr. Both streams are searched rather
    # than guessing which one a given tool chose.
    return f"{completed.stdout}\n{completed.stderr}"


def check_tool(requirement: ToolRequirement, runner: CommandRunner = run_command) -> CheckResult:
    """Check one requirement and classify the outcome."""
    output = runner([requirement.executable, *requirement.version_args])
    if output is None:
        return CheckResult(requirement, Status.MISSING)

    version = parse_version(output)
    if version is None:
        return CheckResult(requirement, Status.UNREADABLE, found_version=output.strip()[:40])

    rendered = ".".join(str(part) for part in version)

    if requirement.minimum_version is None:
        return CheckResult(requirement, Status.OK, found_version=rendered)

    # Compare on the shorter length: a minimum of (20,) must accept 20.11.0, and
    # comparing (20,) with (20, 11, 0) directly would report it as too old.
    depth = len(requirement.minimum_version)
    if version[:depth] < requirement.minimum_version:
        return CheckResult(requirement, Status.OUTDATED, found_version=rendered)

    return CheckResult(requirement, Status.OK, found_version=rendered)


def format_report(results: Sequence[CheckResult]) -> str:
    """Render the results as a plain-text report.

    Deliberately ASCII and unstyled: this output is read in PowerShell, in
    Windows Terminal, in a Dev Container, and pasted into issues. Colour codes
    and box-drawing characters survive none of those reliably.
    """
    lines = [
        "Enterprise Multi-Agent AI Platform - environment check",
        "=" * 60,
        "",
    ]

    name_width = max(len(result.requirement.name) for result in results)

    for result in results:
        requirement = result.requirement
        necessity = "required" if requirement.required else "optional"
        version = result.found_version or "not found"
        lines.append(
            f"  [{result.status.symbol}] {requirement.name:<{name_width}}  "
            f"{version:<12}  ({necessity})"
        )

    problems = [result for result in results if result.status is not Status.OK]
    if problems:
        lines.extend(["", "-" * 60, ""])
        for result in problems:
            requirement = result.requirement
            if result.status is Status.OUTDATED:
                minimum = ".".join(str(part) for part in requirement.minimum_version or ())
                headline = f"{requirement.name} {result.found_version} is older than {minimum}"
            elif result.status is Status.MISSING:
                headline = f"{requirement.name} was not found on PATH"
            else:
                headline = f"{requirement.name} reported a version this script cannot read"

            lines.append(f"  {headline}")
            lines.append(f"    Needed for: {requirement.purpose}")
            lines.append(f"    Install:    {requirement.install_hint}")
            lines.append("")

    blocking = [result for result in results if result.blocks_setup]
    lines.extend(["-" * 60, ""])
    if blocking:
        names = ", ".join(result.requirement.name for result in blocking)
        lines.append(f"  Setup cannot continue. Missing or outdated: {names}")
    else:
        optional_gaps = [
            result.requirement.name
            for result in problems
            if not result.requirement.required and result.status is Status.MISSING
        ]
        if optional_gaps:
            lines.append(f"  Ready. Optional tools not installed: {', '.join(optional_gaps)}")
        else:
            lines.append("  Ready. Every tool is present and recent enough.")

    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Check every requirement and print the report.

    Returns:
        ``0`` when nothing required is missing or outdated, ``1`` otherwise —
        so a bootstrap script can stop on the exit code rather than parse this
        output.
    """
    del argv  # No options yet. Accepted so the signature can gain them.

    results = [check_tool(requirement) for requirement in REQUIREMENTS]
    sys.stdout.write(format_report(results))
    return 1 if any(result.blocks_setup for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
