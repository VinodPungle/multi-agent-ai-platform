# ADR-0012: Durable conversation memory on Redis, authenticated by Entra ID

- **Status:** Accepted
- **Date:** 2026-08-09
- **Deciders:** Platform architecture
- **Supersedes:** nothing
- **Related:** [ADR-0004](0004-provider-abstraction-via-protocols.md) (protocols),
  [ADR-0006](0006-llm-gateway-and-provider-neutral-contract.md) (gateway)

---

## Context

Until Milestone 09 the platform's only `MemoryProvider` was
`InMemorySessionMemoryProvider`: a bounded dictionary in the process.

That is the correct first implementation, and it was never going to be the last
one. Three properties made it wrong for the deployed platform:

1. **History dies with the process.** Container Apps restarts a revision on
   every deployment, and development and testing scale to zero on idle. A
   conversation is discarded at both moments, and neither is one a user chose.
2. **History is not shared.** `backendMaxReplicas` is 3 in development and 10 in
   production. A user's follow-up question lands on whichever replica the
   ingress picks, and only one of them has heard of them. The failure is
   intermittent, load-dependent, and invisible on a single-replica laptop —
   the worst combination for something to find in production.
3. **Nothing else can read it.** Evaluation, analytics and any future
   human-in-the-loop review all need conversation history from outside the
   process that produced it.

`architecture.md` calls memory a platform capability rather than an agent
capability, and `CLAUDE.md` lists Redis first among the intended
implementations. This ADR records the decision to build it and, more
substantially, how it authenticates.

## Decision

### Redis, as a list per conversation

One key per conversation, `maap:conversation:<id>`, holding serialised messages
in order.

`append` is the hot path — two writes per turn — and `RPUSH` is O(1) with no
read-modify-write. The obvious alternative, storing a conversation as a single
serialised blob, makes every append a read, a decode, a re-encode and a write,
and loses a message whenever two requests for one conversation overlap. That
race is rare, silent, and exactly the kind of thing that only happens under
load.

`LTRIM` after each push enforces the message cap in the same round trip.

### Expiry rather than eviction

Each conversation carries a TTL, refreshed on every write.

The in-process provider needs an LRU cap because the process's memory is finite
and shared with everything else in it. Redis has its own memory budget and its
own eviction policy, so the platform's job changes: it says how long a
conversation is *worth* keeping, and lets Redis decide what to do under
pressure. The cache is configured `allkeys-lru` so that genuine pressure drops
the oldest history rather than refusing writes mid-turn.

### Failure degrades, it does not propagate

Reads return empty. Writes are logged and swallowed. `health_check` reports
**DEGRADED**, not UNHEALTHY.

This is the decision most worth defending, because the alternative looks more
rigorous. A memory backend that is unreachable must not take chat down with it:
losing history is visible to the user and survivable, whereas a failed turn is
neither. Reporting UNHEALTHY would fail the readiness probe and remove a replica
that can still answer every request — turning a degraded cache into an outage.

### Authentication is Entra ID, not an access key

The conventional pattern is to put the cache's primary key in Key Vault,
reference it from the Container App, and interpolate it into a connection URL.
It works. It also means the platform holds a long-lived credential for a service
that does not require one, in a string that gets logged by accident and copied
into laptops.

`CLAUDE.md` is unambiguous — Managed Identity, no keys — and Azure Cache for
Redis supports Entra ID on the data plane. So:

- The cache is provisioned with `aad-enabled` and a **Data Owner** access policy
  assignment for the workload identity.
- The application connects with a redis-py credential provider that returns
  `(object_id, access_token)`, acquired through the same
  `DefaultAzureCredential` chain everything else uses.
- No Redis secret exists in Key Vault, in a deployment output, in an environment
  variable, or in the repository.

Access keys are **not disabled**, because the classic Azure Cache for Redis
service offers no switch to disable them — that arrived with Azure Managed
Redis. Nothing in the platform uses them. This is a real limitation and is
recorded rather than glossed.

## Consequences

### Good

- Conversations survive restarts, deployments and scale-to-zero.
- Replicas share history, so scaling out stops being a correctness risk.
- No new secret. The deployment's secret inventory is unchanged.
- The `MemoryProvider` interface did not move. No agent, no runtime code and no
  workflow knows which backend it has — which is the property the interface was
  written for, now demonstrated rather than asserted.

### Bad, or at least costly

- **A cache bills continuously.** `provisionRedis` therefore defaults to
  `false`, and development and testing leave it off. Durable memory is a
  deliberate purchase per environment, not a default.
- **Tokens expire under a live connection.** redis-py authenticates when a
  connection is established, not continuously, so Azure closes a pooled
  connection when its token expires. This is handled rather than avoided:
  retries plus a health-check interval mean a reconnect acquires a fresh token
  and the operation proceeds. It is a real sharp edge and it is documented in
  `entra_credentials.py`.
- **Two authentication paths exist.** `url` for local and Compose, `entra` for
  Azure. A single path would be cleaner, but the alternatives were a cloud
  dependency to run the test suite, or a production-only code path — both worse
  than one setting.
- **`search` is recency, not relevance.** The contract permits a documented
  fallback and this is one. Semantic search needs an embedding provider and a
  vector index; when those exist it becomes a different provider, not a flag on
  this one.

### Neutral

- `fakeredis` covers the suite in CI, and the provider was additionally verified
  against a real `redis:7-alpine`. The second step was not ceremony: this
  project has three recorded instances of a test double being more accommodating
  than the real thing, and durability across a *new connection* is precisely
  what a fake cannot honestly demonstrate.

## Alternatives considered

**PostgreSQL.** Durable, transactional, already understood by every engineer.
Rejected for the hot path: conversation append is a high-frequency, small,
last-N-wins operation, which is a list, not a table. It remains the right
backend for the *audit* copy of a conversation, which is a different concern
and a later provider.

**Cosmos DB.** Globally distributed and genuinely attractive for multi-region.
Rejected as premature — the platform is single-region by explicit scope, and
Cosmos's cost model punishes the write-heavy, read-heavy pattern here far more
than a cache does.

**Azure Managed Redis (Redis Enterprise).** Supports disabling access keys
outright, which would remove the caveat above. Rejected on cost: its entry SKU
is several times the price of Standard C0 for a workload measured in kilobytes.
Revisit if the platform ever needs active geo-replication.

**Sticky sessions instead of shared memory.** Pin a conversation to a replica
and keep the in-process provider. Rejected: it makes a deployment or a scaling
event lose conversations rather than fixing anything, and it couples correctness
to ingress configuration nobody would think to check.
