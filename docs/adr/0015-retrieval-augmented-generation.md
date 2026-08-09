# ADR-0015: Retrieval-augmented generation, with retrieval as a tool

- **Status:** Accepted
- **Date:** 2026-08-09
- **Deciders:** Platform architecture
- **Supersedes:** nothing
- **Related:** [ADR-0010](0010-tool-framework-and-internet-search.md) (tool framework),
  [ADR-0012](0012-durable-conversation-memory.md) (memory), [ADR-0014](0014-mcp-tools-as-an-adapter.md) (MCP)

---

## Context

`CLAUDE.md` lists RAG, embeddings and vector databases among the capabilities
the architecture must not prevent, and the SDK has carried `EmbeddingProvider`
and `VectorStoreProvider` since Milestone 01 for exactly that reason. This ADR
records building on them.

The question that shaped everything else was not which vector database to use.
It was **where retrieval happens in a turn**.

## Decision

### Retrieval is a tool, not a prompt preamble

The common pattern is: take the user's message, retrieve passages, prepend them
to the prompt, call the model. It is simple and it is wrong for this platform.

Making retrieval a tool means:

- **The model decides when documents are needed.** A turn that needs none costs
  one model call and spends no context on passages nobody asked for. A preamble
  retrieves on every turn including "thanks, that's helpful".
- **The runtime governs it.** Authorisation, timeout, retry, telemetry and
  budget apply to retrieval exactly as to every other tool, because it *is*
  every other tool. A preamble sits outside all of that.
- **Access is configuration.** An agent that must not see internal documents
  does not list the tool.
- **The query is visible.** The model formulates it, and it is reported — so a
  user can see what was actually searched for, rather than assuming their words
  were used verbatim.

The cost is that the model has to choose to search, which is prompt engineering.
That is the same trade already accepted for internet search, and the tool
description states the distinction between internal documents and the public
internet explicitly for that reason.

### A score threshold, and why it is the most important setting

A vector search always returns its `limit` nearest neighbours. On a corpus with
nothing to say about the question, the nearest neighbours are still returned and
they look exactly like an answer. Handing those to a model invites it to ground
a confident reply in whatever text happened to be least unlike the question.

`minimum_score` turns that into an empty result, which the tool reports honestly
and the model can act on. It defaults to `0` — not because zero is right, but
because score semantics differ between providers and a non-zero default would
look authoritative while being meaningless against any store but the one it was
tuned on.

### Chunking on structure, in characters

Paragraphs, then sentences, then a hard cut. A boundary chosen by the author
beats one chosen by a character count.

**Characters, not tokens**, deliberately: the platform has no tokenizer, a
tokenizer is model-specific, and chunk boundaries would then shift whenever the
model changed — silently re-shaping an index that had already been built.

Adjacent chunks overlap, because a sentence that answers the question sitting on
a boundary would otherwise be split across two passages, each holding half an
answer and matching neither.

### Two embedding providers, one of them honest about being fake

`HashingEmbeddingProvider` computes lexical embeddings locally — character
trigrams hashed into dimensions. No model, no network, no cost. It makes the
whole pipeline runnable on a laptop and in CI, which is what `CLAUDE.md`
requires of every capability.

It is **not semantic**. It matches shared character sequences, so "car" and
"automobile" are unrelated to it. That is stated in the class docstring, in its
health check output, in the settings description, and here — because the failure
mode of a plausible fake is that somebody eventually believes it. The
composition root refuses it in production-like environments, mirroring the mock
LLM provider.

A sentence-transformer would be genuinely semantic and costs a few hundred
megabytes of PyTorch in every container and CI run. For a development default
whose job is to make the pipeline runnable, that is a large price for a property
nobody should be relying on in development.

### An in-process vector store first

Brute-force cosine similarity over vectors held in the process. Exact, not
approximate.

An approximate index (HNSW, IVF) earns its complexity in the hundreds of
thousands of vectors; below that it is slower to build, harder to reason about,
and can miss the best match. For a corpus that fits in a process, exact search
is both simpler and better. The scale where that reverses is where Azure AI
Search replaces this behind the same interface.

Vectors are normalised once on write, so a query is a dot product rather than
two norms and a division per candidate.

### Indexing at startup, from a directory in the repository

A corpus versioned alongside the code is reviewable in a pull request,
reproducible in every environment, and present in the image — no upload step and
no second store to keep in sync.

Indexing runs **synchronously with startup** so the platform is either ready to
answer from its documents or has said clearly why not. Indexing in the
background would make the first requests after a deployment silently
unanswerable, because retrieval returning nothing is indistinguishable from a
corpus with nothing to say.

Record ids are `<document_id>#<chunk_index>` and document ids are repository-
relative paths, so re-indexing **replaces** a document's passages rather than
adding near-duplicates that then compete with the originals in every search. A
document that gets shorter has its orphaned tail deleted explicitly.

## Consequences

### Good

- A working RAG pipeline with nothing provisioned and nothing billed.
- Retrieval inherits every runtime policy for free, and is per-agent by
  configuration.
- Swapping either provider is a configuration change; no calling code names an
  embedding model or a vector database.
- Ingestion is safe to re-run, which is what makes it something anyone will
  actually re-run.

### Bad, or at least costly

- **The development embedder is lexical.** Any retrieval-quality judgement made
  against it is a judgement about string overlap. The tests are written to
  assert what it genuinely does and no more — there is deliberately no test
  claiming a paraphrased question finds the right passage.
- **The vector store is neither durable nor shared.** The index is rebuilt on
  every start and every replica holds its own copy. Fine for a corpus in the
  repository; wrong for a large or externally-sourced one. Same trajectory as
  memory, and the interface makes it the same kind of change.
- **Startup cost scales with the corpus.** Embedding a large corpus at every
  start costs money and time. Off by default, and the document and passage
  counts are logged so an unexpected number is visible immediately.
- **Text formats only.** PDF and DOCX need a parser, and a bad parser produces
  text that looks fine and has lost its structure — tables flattened into word
  soup, headings inlined. Skipped with a warning rather than half-read.
- **No reranking, no hybrid search, no query rewriting.** Each is a real
  improvement and each is a separate decision; the pipeline has the seams for
  all three.

### Neutral

- `Capability.EMBEDDINGS` finally has a producer, six milestones after being
  declared.

## Alternatives considered

**Prepend retrieved passages to every prompt.** Simpler, and the usual tutorial
shape. Rejected above: it spends context on turns that need none, sits outside
every runtime policy, and gives the model no way to say what it searched for.

**Azure AI Search from the start.** Durable, shared, hybrid search, and the
obvious production answer. Rejected as the *first* implementation for the same
reason in-memory memory came before Redis: it makes the pipeline undevelopable
without a provisioned resource, and it would have been written against an SDK
with no live instance to verify against — which this project has been burned by
twice. The interface makes it an additive change.

**A local sentence-transformer as the development embedder.** Genuinely
semantic. Rejected on weight: hundreds of megabytes of PyTorch plus a model
download in every container and CI run, to provide a property that should not be
relied on in development anyway.

**Token-based chunking with a real tokenizer.** More accurate sizing. Rejected
because it is model-specific: chunk boundaries would change with the model, and
an index built under one would be subtly wrong under another.

**Storing passage text in the vector store's metadata versus re-reading source
files at query time.** Metadata was chosen. Re-reading would keep the index
smaller and make every retrieval depend on files still existing, unchanged, at
the paths they had when indexed — which is exactly the assumption that breaks
after a deployment.
