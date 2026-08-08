"""Remove build, test and type-check caches.

    uv run python scripts/clean.py

Python rather than a shell one-liner because ``rm -rf`` and ``Remove-Item`` are
not the same command, and this repository is developed on both. A caches-only
scope is deliberate: nothing here removes ``.venv`` or ``node_modules``, which
are expensive to rebuild and never the cause of the problem someone is trying to
clear.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

__all__ = ["CACHE_DIRECTORY_NAMES", "CACHE_FILE_NAMES", "clean", "main"]

#: Directories removed wherever they appear, at any depth.
CACHE_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
    }
)

#: Files removed from the repository root only.
CACHE_FILE_NAMES: frozenset[str] = frozenset({".coverage", "coverage.xml", "junit.xml"})

#: Never descended into. Walking a `node_modules` tree takes far longer than
#: everything else this script does put together, and holds no caches of ours.
_SKIP_DIRECTORY_NAMES: frozenset[str] = frozenset({".git", ".venv", "node_modules"})


def clean(root: Path) -> list[Path]:
    """Delete cache directories and files under ``root``.

    Args:
        root: Repository root to clean.

    Returns:
        The paths that were removed, for reporting.
    """
    removed: list[Path] = []

    for path in sorted(root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if not path.is_dir():
            continue
        if any(part in _SKIP_DIRECTORY_NAMES for part in path.parts):
            continue
        if path.name in CACHE_DIRECTORY_NAMES:
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path)

    for name in sorted(CACHE_FILE_NAMES):
        candidate = root / name
        if candidate.is_file():
            candidate.unlink()
            removed.append(candidate)

    return removed


def main() -> int:
    """Clean the repository this script lives in."""
    root = Path(__file__).resolve().parent.parent
    removed = clean(root)

    for path in removed:
        sys.stdout.write(f"removed {path.relative_to(root)}\n")
    sys.stdout.write(f"{len(removed)} cache path(s) removed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
