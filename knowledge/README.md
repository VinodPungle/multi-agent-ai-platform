# Knowledge base

Documents indexed at startup and searchable by agents through the
`knowledge-search` tool.

Everything here is chunked, embedded and indexed when
`PLATFORM_KNOWLEDGE__ENABLED=true`. Nothing is indexed otherwise, and the tool
is not registered — a tool that exists and always returns nothing teaches a
model to stop calling it.

## What belongs here

Information specific to *this* organisation, which is the distinction the tool's
description draws for the model: internal policies, runbooks, architecture
notes, product documentation. Anything a public search engine could answer
belongs to `internet-search` instead.

## Formats

Markdown, plain text and reStructuredText. PDF and DOCX are deliberately not
supported: they need a parser, and a bad parser produces text that looks fine
and has lost its structure — tables flattened into word soup, headings inlined.

## Identity and re-indexing

A document's id is its path relative to this directory, so re-indexing a changed
file **replaces** its passages rather than adding a second copy that competes
with the first in every search. Renaming a file creates a new document; the old
one persists until the index is rebuilt.

## Titles

The first Markdown heading becomes the title cited back to the user. A citation
reading "Expense Policy" is worth more than one reading
`policies/expenses-v2-final.md`, and the file already says which it is.
