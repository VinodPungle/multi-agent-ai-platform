"""Splitting documents into retrievable passages.

The least glamorous part of RAG and the one that decides whether it works. A
retriever can only return what chunking produced: split too small and a passage
loses the context that made it meaningful, split too large and the match is
diluted by surrounding text and the passage costs more of the prompt than it is
worth.

Two decisions carry that trade:

**Split on structure before length.** Paragraphs first, then sentences, then —
only if something is still too long — a hard cut. A boundary chosen by the
author is almost always better than one chosen by a character count, and the
cost of preferring it is a few lines.

**Overlap between chunks.** A sentence that answers the question sitting exactly
on a boundary would otherwise be split across two passages, each holding half an
answer and matching neither. Overlap is the cheapest insurance against that, and
it costs storage rather than accuracy.

Measured in characters, not tokens, and deliberately: the platform has no
tokenizer, a tokenizer is model-specific, and chunk boundaries would then change
whenever the model did — silently re-shaping an index that had already been
built.
"""

from __future__ import annotations

import re
from itertools import pairwise

from agent_platform_sdk.dto.knowledge import KnowledgeDocument

__all__ = ["Chunk", "chunk_document"]

#: Paragraph boundaries: a blank line, however much whitespace it carries.
_PARAGRAPH = re.compile(r"\n\s*\n")

#: Sentence boundaries. Deliberately simple — a full parser would be a
#: dependency and a class of bug for a marginal gain, and a wrong split here
#: costs a slightly worse passage rather than a wrong answer.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class Chunk:
    """One passage of a document, with its position.

    A plain class: chunking runs over whole corpora in batches, and validating
    every chunk would cost measurably for a shape this module produced itself.
    """

    __slots__ = ("content", "index")

    def __init__(self, content: str, index: int) -> None:
        self.content = content
        self.index = index

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Chunk(index={self.index}, chars={len(self.content)})"


def chunk_document(
    document: KnowledgeDocument,
    max_characters: int = 1_200,
    overlap_characters: int = 150,
) -> tuple[Chunk, ...]:
    """Split ``document`` into overlapping passages.

    Args:
        document: What to split.
        max_characters: Largest passage to produce. Roughly 300 tokens at four
            characters per token — enough to hold an argument, small enough that
            several fit in a prompt alongside the conversation.
        overlap_characters: How much of the previous passage to repeat at the
            start of the next. Zero disables overlap.

    Returns:
        Passages in document order. A document short enough to fit is returned
        as a single chunk rather than being split for consistency's sake.
    """
    text = document.content.strip()
    if not text:
        return ()

    if len(text) <= max_characters:
        return (Chunk(text, 0),)

    pieces = _split_to_size(text, max_characters)
    merged = _merge_to_size(pieces, max_characters)
    overlapped = _apply_overlap(merged, overlap_characters, max_characters)

    return tuple(Chunk(content, index) for index, content in enumerate(overlapped))


def _split_to_size(text: str, max_characters: int) -> list[str]:
    """Break text into pieces no larger than ``max_characters``.

    Structure first: paragraphs, then sentences within an oversized paragraph,
    then a hard cut for anything still too long — a minified file, a base64
    blob, a language this splitter does not understand.
    """
    pieces: list[str] = []

    for paragraph in _PARAGRAPH.split(text):
        candidate = paragraph.strip()
        if not candidate:
            continue
        if len(candidate) <= max_characters:
            pieces.append(candidate)
            continue

        for raw_sentence in _SENTENCE.split(candidate):
            sentence = raw_sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= max_characters:
                pieces.append(sentence)
                continue
            # Still too long: a hard cut. Ugly, and better than a passage that
            # cannot be embedded or that swamps the prompt.
            pieces.extend(
                sentence[start : start + max_characters]
                for start in range(0, len(sentence), max_characters)
            )

    return pieces


def _merge_to_size(pieces: list[str], max_characters: int) -> list[str]:
    """Recombine adjacent pieces up to the size limit.

    Splitting on paragraphs alone would emit a chunk per paragraph, and a
    document of one-line paragraphs would produce dozens of passages too small
    to mean anything. Merging restores useful size while keeping every boundary
    on a structural break.
    """
    merged: list[str] = []
    current = ""

    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + len(piece) + 2 <= max_characters:
            current = f"{current}\n\n{piece}"
        else:
            merged.append(current)
            current = piece

    if current:
        merged.append(current)

    return merged


def _apply_overlap(chunks: list[str], overlap: int, max_characters: int) -> list[str]:
    """Prefix each chunk with the tail of the one before it.

    Guards the answer that falls on a boundary. Bounded to a third of the chunk
    size regardless of what was configured: beyond that the index is storing
    mostly duplicates, and retrieval starts returning the same text under
    several ids.
    """
    if overlap <= 0 or len(chunks) < 2:
        return chunks

    effective = min(overlap, max_characters // 3)
    overlapped = [chunks[0]]

    for previous, chunk in pairwise(chunks):
        tail = previous[-effective:].lstrip()
        overlapped.append(f"{tail}\n\n{chunk}" if tail else chunk)

    return overlapped
