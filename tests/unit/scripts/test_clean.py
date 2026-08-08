"""Cache cleaning behaviour.

A cleaning script is exactly the kind of code that is never tested and
occasionally deletes something it should not. These tests run against a
temporary tree, so a mistake in the traversal shows up here rather than in
someone's working copy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clean import clean

pytestmark = pytest.mark.unit


def build_tree(root: Path) -> None:
    """Create a repository-shaped tree containing caches and real source."""
    (root / "src" / "backend" / "agent_platform" / "__pycache__").mkdir(parents=True)
    (root / "src" / "backend" / "agent_platform" / "__pycache__" / "app.pyc").touch()
    (root / "src" / "backend" / "agent_platform" / "app.py").touch()

    (root / ".mypy_cache").mkdir()
    (root / ".mypy_cache" / "index.json").touch()
    (root / ".pytest_cache").mkdir()
    (root / ".ruff_cache").mkdir()

    (root / "coverage.xml").touch()
    (root / ".coverage").touch()

    (root / ".venv" / "Lib" / "__pycache__").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "__pycache__").mkdir(parents=True)
    (root / ".git" / "objects").mkdir(parents=True)


class TestClean:
    def test_cache_directories_are_removed(self, tmp_path: Path) -> None:
        build_tree(tmp_path)

        clean(tmp_path)

        assert not (tmp_path / ".mypy_cache").exists()
        assert not (tmp_path / ".pytest_cache").exists()
        assert not (tmp_path / ".ruff_cache").exists()
        assert not (tmp_path / "src/backend/agent_platform/__pycache__").exists()

    def test_cache_files_are_removed(self, tmp_path: Path) -> None:
        build_tree(tmp_path)

        clean(tmp_path)

        assert not (tmp_path / "coverage.xml").exists()
        assert not (tmp_path / ".coverage").exists()

    def test_source_is_left_alone(self, tmp_path: Path) -> None:
        build_tree(tmp_path)

        clean(tmp_path)

        assert (tmp_path / "src/backend/agent_platform/app.py").exists()

    def test_expensive_directories_are_never_touched(self, tmp_path: Path) -> None:
        """Rebuilding `.venv` or `node_modules` costs minutes and fixes nothing."""
        build_tree(tmp_path)

        clean(tmp_path)

        assert (tmp_path / ".venv/Lib/__pycache__").exists()
        assert (tmp_path / "node_modules/pkg/__pycache__").exists()
        assert (tmp_path / ".git/objects").exists()

    def test_the_removed_paths_are_reported(self, tmp_path: Path) -> None:
        build_tree(tmp_path)

        removed = clean(tmp_path)

        assert (tmp_path / ".mypy_cache") in removed
        assert (tmp_path / "coverage.xml") in removed

    def test_cleaning_a_clean_tree_removes_nothing(self, tmp_path: Path) -> None:
        """Idempotent: running it twice is not an error."""
        build_tree(tmp_path)
        clean(tmp_path)

        assert clean(tmp_path) == []
