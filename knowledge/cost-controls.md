# Cost Controls

Cost is treated as an architectural concern rather than an operational metric.

## Budget policy

Each agent may declare maximum tokens, maximum cost, maximum execution time and
maximum tool invocations. The runtime enforces these before a turn starts and
again after it completes. A turn that would breach a budget is refused before a
model is called, because refusing afterwards has already spent the money.

## Scale to zero

Development and testing environments scale their container apps to zero
replicas when idle. Production keeps one warm replica, because a cold start on a
user's first request is a worse experience than the idle cost of one instance.

## Telemetry sampling

Trace sampling is the main telemetry cost lever. At a sampling ratio of 1 every
request is traced, and telemetry volume becomes a significant line on the bill
well before inference does. Lowering the ratio keeps enough signal to diagnose a
pattern while costing proportionally less.

## Conversation memory

Azure Cache for Redis bills continuously and has no idle state, so durable
conversation memory is provisioned per environment rather than by default.
Development and testing use in-process memory.

## Knowledge indexing

Embedding a corpus costs money proportional to its size. Indexing runs once at
startup rather than per request, documents are re-indexed by stable id so a
rebuild does not duplicate them, and the document and passage counts are logged
so an unexpected number is visible immediately.
