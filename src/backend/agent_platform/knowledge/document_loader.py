"""Reading a corpus off disk.

The simplest ingestion source there is, and deliberately the first one: a
directory of Markdown and text files, versioned alongside the code. That makes a
corpus reviewable in a pull request, reproducible in every environment, and
present in the container image — no upload step, no separate store to keep in
sync, nothing to configure before the platform can answer a question about
itself.

It is not the only source anyone will want. SharePoint, Confluence, a database,
an upload endpoint — each is a different implementation of "produce
``KnowledgeDocument`` values", and each can be added without touching the
indexer, the retriever or the tool. That is the reason this module returns
documents rather than indexing them.

Binary formats are out of scope
    PDF and DOCX need a parser, and a bad parser produces text that looks fine
    and has lost its structure — tables flattened into word soup, headings
    inlined. A file this loader cannot read is skipped with a warning rather
    than half-read, because half-read is the failure nobody notices.
"""

from __future__ import annotations

from pathlib import Path

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.dto.knowledge import KnowledgeDocument

__all__ = ["SUPPORTED_SUFFIXES", "load_documents", "resolve_documents_directory"]

_logger = get_logger(__name__)

#: What this loader will read. Text formats only — see the module docstring.
SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst"})

#: Files larger than this are skipped. A corpus is prose; a file this size is
#: almost always a log, a dump or a checked-in artefact, and embedding it would
#: spend real money producing passages nobody wants returned.
_MAX_FILE_BYTES = 2_000_000


def resolve_documents_directory(configured: str) -> Path:
    """Locate the corpus directory.

    The same three-step resolution as the prompts directory, for the same
    reason: a relative path resolves against the working directory, and the
    working directory differs between a developer's shell, a test run and a
    container. Getting this wrong produced a platform that reported healthy with
    zero prompts once already.

    Absolute, then relative to the working directory, then searched for among
    this file's ancestors.
    """
    candidate = Path(configured)
    if candidate.is_absolute():
        return candidate

    from_cwd = Path.cwd() / candidate
    if from_cwd.is_dir():
        return from_cwd

    for ancestor in Path(__file__).resolve().parents:
        possible = ancestor / candidate
        # Skip anything that is a Python package: `knowledge` is also the name
        # of this module's own package, and matching it would point the loader
        # at source code. Exactly the trap the prompts resolver hit.
        if possible.is_dir() and not (possible / "__init__.py").exists():
            return possible

    return from_cwd


def load_documents(directory: Path) -> tuple[KnowledgeDocument, ...]:
    """Read every supported file under ``directory``, recursively.

    A missing directory returns nothing rather than raising: an environment with
    no corpus is a legitimate state, and it is reported by the indexer's log
    line and the tool returning no passages.
    """
    if not directory.is_dir():
        _logger.warning(
            "knowledge.directory_missing",
            directory=str(directory),
            detail="No documents were indexed. Knowledge search will return nothing.",
        )
        return ()

    documents: list[KnowledgeDocument] = []

    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue

        if path.stat().st_size > _MAX_FILE_BYTES:
            _logger.warning(
                "knowledge.file_too_large",
                source=_relative(path, directory),
                bytes=path.stat().st_size,
                detail="Skipped. A corpus is prose; this is almost certainly not.",
            )
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            # Skipped, not fatal: one unreadable file must not stop a corpus
            # from being indexed, and silence would be worse than either.
            _logger.warning(
                "knowledge.file_unreadable",
                source=_relative(path, directory),
                error_type=type(error).__name__,
            )
            continue

        if not content.strip():
            continue

        source = _relative(path, directory)
        documents.append(
            KnowledgeDocument(
                # The path, so re-indexing a changed file replaces its passages
                # rather than adding a second copy that competes with the first.
                document_id=source,
                title=_title_of(content, path),
                content=content,
                source=source,
            )
        )

    _logger.info(
        "knowledge.documents_loaded",
        directory=str(directory),
        document_count=len(documents),
    )
    return tuple(documents)


def _relative(path: Path, root: Path) -> str:
    """Return a stable, portable identifier for a file.

    Relative and forward-slashed, so a document id does not change between a
    developer's machine and a container — which would silently duplicate the
    whole corpus on the first deployment.
    """
    return path.relative_to(root).as_posix()


def _title_of(content: str, path: Path) -> str:
    """Return a human title, preferring the document's own first heading.

    A citation reading "Expense Policy" is worth more to a user than one reading
    "policies/expenses-v2-final.md", and the file already says which it is.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
        if stripped:
            # Content before any heading: stop looking rather than scanning a
            # whole file for a heading that is not there.
            break

    return path.stem.replace("-", " ").replace("_", " ").title()
