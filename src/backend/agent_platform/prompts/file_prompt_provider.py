"""Prompt assets loaded from the filesystem.

The first :class:`~agent_platform_sdk.interfaces.prompt_provider.PromptProvider`.
It reads the versioned Markdown files under ``/prompts``, each carrying YAML front
matter that mirrors :class:`PromptAsset`.

Loaded once at startup, not per request
    A prompt is read on every model call. Reading a file each time would put disk
    I/O on the hot path to save a few kilobytes of memory, and would make a
    half-written file during a deploy a request failure rather than a startup
    failure. Reloading is a restart, which is also what makes the prompt a
    deployed artefact rather than mutable state.

Versioning
    A file declares its own ``version``. Several files may share a ``prompt_id``
    with different versions, which is how an agent pins one for reproducibility
    while others move on. Two files declaring the *same* id and version is a
    conflict and refuses to start — the alternative is that whichever the
    filesystem happened to yield last wins, and that differs between machines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_platform.exceptions.base import ConfigurationError, NotFoundError
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.prompt import PromptAsset
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["FilePromptProvider", "resolve_prompts_directory"]

_logger = get_logger(__name__)

#: Separates YAML front matter from the template body.
_FRONT_MATTER_DELIMITER = "---"

#: How far above this module to look for a configured relative directory.
#: Five levels reaches the repository root from
#: ``src/backend/agent_platform/prompts/`` and stops there, so the search can
#: never wander into a same-named directory outside the project.
_ANCESTOR_SEARCH_LIMIT = 5


def resolve_prompts_directory(configured: str | Path) -> Path:
    """Turn a configured prompts path into an absolute one.

    A relative path is resolved against the *working directory*, which is not a
    property of the deployment — it is a property of however the process was
    launched. A backend started from one directory up loaded no prompts, showed
    a green dashboard, and answered every request with "No prompt registered".
    Nothing in the configuration was wrong.

    Resolution order:

    1. An absolute path is used exactly as given. Explicit configuration always
       wins, including when it points somewhere empty — that is a real
       misconfiguration and must stay visible.
    2. A relative path that exists relative to the working directory is used.
       This is the container case: ``WORKDIR /app`` with ``/app/prompts``.
    3. Otherwise the same relative path is looked for above this module, which
       finds the repository's own ``prompts/`` regardless of where the process
       started.

    The fallback only runs when the configured path does not exist, so it can
    never override a deliberate choice — it only rescues a launch-location
    accident.

    Args:
        configured: The path as configured, absolute or relative.

    Returns:
        An absolute path. It may still not exist; the caller reports that as
        unhealthy rather than guessing further.
    """
    path = Path(configured)

    if path.is_absolute():
        return path

    if path.is_dir():
        return path.resolve()

    for ancestor in list(Path(__file__).resolve().parents)[:_ANCESTOR_SEARCH_LIMIT]:
        candidate = ancestor / path
        # A directory holding `__init__.py` is a Python package, not an asset
        # directory. This is not hypothetical: the module implementing this
        # function lives in a package called `prompts`, so an unguarded search
        # for a directory named `prompts` matches the source tree first and
        # loads nothing.
        if candidate.is_dir() and not (candidate / "__init__.py").exists():
            _logger.info(
                "prompts.directory_resolved_from_package",
                configured=str(path),
                resolved=str(candidate),
                working_directory=str(Path.cwd()),
                detail=(
                    "The configured relative path does not exist in the working "
                    "directory. Using the copy found alongside the package."
                ),
            )
            return candidate

    # Resolved for the error message: a relative path in a log line is useless
    # without knowing what it was relative to.
    return path.resolve()


class FilePromptProvider:
    """Serves prompt assets read from a directory tree.

    Satisfies :class:`PromptProvider` structurally.
    """

    def __init__(self, root: Path, provider_id: str = "file-prompts") -> None:
        """Create the provider.

        Args:
            root: Directory to scan, recursively, for ``*.md`` prompt files.
            provider_id: Identifier it registers under.
        """
        self._root = root
        self._provider_id = provider_id
        # (prompt_id, version) -> asset. Versions of one prompt sort newest
        # first in `_versions`, which is the order rollback tooling wants.
        self._assets: dict[tuple[str, str], PromptAsset] = {}
        self._versions: dict[str, list[str]] = {}

    # -- Provider ----------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    async def initialize(self) -> None:
        """Load every prompt under the root directory.

        Raises:
            ConfigurationError: a file is malformed, or two files declare the
                same id and version. Both are startup failures by design: a
                platform that starts with an unreadable prompt fails later, on
                a user's request, with a far less obvious message.
        """
        if not self._root.is_dir():
            # Not an error. A deployment may legitimately carry no prompts yet,
            # and agents that need one fail individually with a clear message.
            _logger.warning(
                "prompts.directory_missing",
                path=str(self._root),
                detail="No prompt assets loaded. Agents requiring a prompt will fail.",
            )
            return

        for path in sorted(self._root.rglob("*.md")):
            # README and other documentation live alongside the assets.
            if path.name.lower() == "readme.md":
                continue
            self._load(path)

        _logger.info(
            "prompts.loaded",
            provider_id=self._provider_id,
            prompt_count=len(self._versions),
            asset_count=len(self._assets),
            root=str(self._root),
        )

    async def health_check(self) -> ComponentHealth:
        """Report how many assets are held, and refuse to call zero healthy.

        Nothing here can become unreachable after startup — the assets are in
        memory — so the only interesting question is whether any were found.

        An empty registry is reported UNHEALTHY rather than healthy-with-zero.
        Every agent turn resolves a prompt, so a provider holding nothing cannot
        serve a single request; calling that healthy tells an operator the
        platform is fine while every chat fails. It happened: a backend started
        from the wrong working directory found no `prompts/` directory, showed a
        green dashboard, and answered nothing.

        The detail names the directory, because the cause is almost always that
        `prompts_directory` is relative and the process started somewhere
        unexpected.
        """
        if not self._assets:
            return ComponentHealth(
                name=self._provider_id,
                status=HealthStatus.UNHEALTHY,
                detail=(
                    f"No prompt assets found under '{self._root}'. Every agent turn "
                    f"needs a prompt, so no request can be served. Check that the "
                    f"process was started from the directory containing that path."
                ),
            )

        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=f"{len(self._assets)} prompt asset(s) across {len(self._versions)} prompt(s)",
        )

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Loading files is not a model capability."""
        del capability
        return False

    async def close(self) -> None:
        """Release the loaded assets."""
        self._assets.clear()
        self._versions.clear()

    # -- Prompts -----------------------------------------------------------

    async def get(self, prompt_id: str, version: str | None = None) -> PromptAsset:
        """Return a prompt asset.

        Args:
            prompt_id: Asset identifier.
            version: Version to return. ``None`` selects the newest.

        Raises:
            NotFoundError: the prompt, or the requested version, is unknown.
        """
        versions = self._versions.get(prompt_id)
        if not versions:
            message = (
                f"No prompt registered under {prompt_id!r}. "
                f"Available: {', '.join(sorted(self._versions)) or 'none'}."
            )
            raise NotFoundError(message, details={"prompt_id": prompt_id})

        resolved = version or versions[0]
        asset = self._assets.get((prompt_id, resolved))
        if asset is None:
            message = (
                f"Prompt {prompt_id!r} has no version {resolved!r}. "
                f"Available versions: {', '.join(versions)}."
            )
            raise NotFoundError(
                message,
                details={"prompt_id": prompt_id, "version": resolved},
            )
        return asset

    async def list_versions(self, prompt_id: str) -> tuple[str, ...]:
        """Return the available versions of a prompt, newest first."""
        return tuple(self._versions.get(prompt_id, ()))

    # -- Loading -----------------------------------------------------------

    def _load(self, path: Path) -> None:
        """Parse one prompt file and index it.

        Raises:
            ConfigurationError: the file is malformed or duplicates an existing
                id and version.
        """
        metadata, template = self._split(path)

        try:
            asset = PromptAsset(**metadata, template=template.strip())
        except Exception as error:
            message = (
                f"Prompt file {path.name} has invalid front matter: {type(error).__name__}. "
                "Every field must match agent_platform_sdk.dto.prompt.PromptAsset."
            )
            raise ConfigurationError(message, details={"path": str(path)}) from error

        key = (asset.prompt_id, asset.version)
        if key in self._assets:
            message = (
                f"Prompt {asset.prompt_id!r} version {asset.version!r} is declared twice. "
                "Publish a new version rather than editing one in place — anything "
                "pinned to a version must keep getting the same text."
            )
            raise ConfigurationError(message, details={"path": str(path)})

        self._assets[key] = asset
        versions = self._versions.setdefault(asset.prompt_id, [])
        versions.append(asset.version)
        # Newest first. Lexicographic rather than semantic: prompt versions are
        # short strings ('1.0', '1.1'), and a full semver parser here would be
        # machinery for a problem that has not appeared.
        versions.sort(reverse=True)

    def _split(self, path: Path) -> tuple[dict[str, Any], str]:
        """Split a prompt file into its front matter and its template.

        Raises:
            ConfigurationError: the file has no front matter or invalid YAML.
        """
        text = path.read_text(encoding="utf-8")

        if not text.lstrip().startswith(_FRONT_MATTER_DELIMITER):
            message = (
                f"Prompt file {path.name} has no YAML front matter. "
                "Every prompt must declare its id and version — see prompts/README.md."
            )
            raise ConfigurationError(message, details={"path": str(path)})

        # Split on the *second* delimiter: the first opens the block, and the
        # body may legitimately contain a `---` horizontal rule.
        _, _, remainder = text.lstrip().partition(_FRONT_MATTER_DELIMITER)
        front_matter, delimiter, template = remainder.partition(f"\n{_FRONT_MATTER_DELIMITER}")

        if not delimiter:
            message = (
                f"Prompt file {path.name} has unterminated front matter. "
                f"The metadata block must be closed with '{_FRONT_MATTER_DELIMITER}'."
            )
            raise ConfigurationError(message, details={"path": str(path)})

        try:
            # `safe_load` never constructs arbitrary Python objects. These files
            # are committed to the repository, but a loader that can instantiate
            # classes from data is a habit worth not having.
            parsed = yaml.safe_load(front_matter)
        except yaml.YAMLError as error:
            message = f"Prompt file {path.name} has invalid YAML front matter."
            raise ConfigurationError(message, details={"path": str(path)}) from error

        if not isinstance(parsed, dict):
            message = f"Prompt file {path.name} front matter must be a YAML mapping."
            raise ConfigurationError(message, details={"path": str(path)})

        return parsed, template
