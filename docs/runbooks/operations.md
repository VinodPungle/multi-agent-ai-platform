# Operations

Day-to-day running of the platform: what to watch, what the numbers should be,
and what to do when they are not.

---

## 1. Is it healthy?

```bash
BACKEND=$(azd env get-value SERVICE_BACKEND_URI)

curl -s "$BACKEND/live"    # the process is running
curl -s "$BACKEND/ready"   # it can serve traffic — 503 if not
curl -s "$BACKEND/health"  # every component, with detail
```

Two components report something less obvious than they appear:

**`azure-foundry` reports configuration, not reachability.** It never calls the
model. A readiness probe that did would wake a scale-to-zero deployment on every
poll and bill for it. Connectivity is proven by the first real request — so
*healthy* here means "correctly configured", and the first chat request is the
real test.

**`file-prompts` reports UNHEALTHY with zero assets.** Every agent turn resolves
a prompt, so a provider holding none cannot serve a single request. This is
deliberately not "healthy with zero", because a green dashboard over a platform
that cannot answer anything is worse than a red one. It has happened.

---

## 2. Performance baseline

Measured against the mock provider with telemetry off, so these are the
platform's *own* overhead — the model's latency is a fact about the model, and
it dominates a real turn so completely that it hides everything else.

| Path | p50 | p95 | p99 |
| --- | --- | --- | --- |
| `GET /live` | 0.85 ms | 1.23 ms | 1.69 ms |
| `GET /health` | 1.15 ms | 1.95 ms | 2.17 ms |
| `POST /chat/messages` | 4.37 ms | 4.89 ms | 5.39 ms |
| Streaming, time to first token | 4.58 ms | 35.1 ms | 35.1 ms |

The streaming p95 is one unwarmed first iteration, not a tail. Read the p50.

**Conversation length costs nothing measurable.** Turn 21 of a conversation was
*faster* than turn 2 (4.32 ms vs 5.02 ms — noise, not an improvement). Session
memory is bounded and in-process, so history does not accumulate cost the way it
would against a database.

Reproduce with the benchmark in the Milestone 08 record. Compare between commits
rather than against absolute numbers: the machine matters more than the change
does.

### What a real turn costs

With a live model, latency is the model's. Observed on `FW-Kimi-K3`:

| | |
| --- | --- |
| Simple answer | ~5.8 s |
| Answer requiring a search | ~15–20 s — a model call to decide, the search, then a second model call |

**A searching turn produces no visible text until the second model call starts.**
That is why the UI emits a `tool` event: several seconds of silence is otherwise
indistinguishable from a hang.

---

## 3. Scaling

| Environment | Min | Max | Rationale |
| --- | --- | --- | --- |
| development, testing | 0 | 2 | Scale to zero. A cold start is acceptable; the idle cost is not |
| staging | 1 | 3 | One warm replica, so a cold start is not mistaken for a regression |
| production | 1 | 10 | Never zero. A cold start on a user's first request is worse than the idle cost |

Scaling is HTTP-concurrency based at 20 concurrent requests per replica. That
number is a starting point, not a measurement — the right value depends on how
long the model takes, and a replica spends nearly all of a chat turn waiting on
the network rather than working.

**Raise `maxReplicas` before raising concurrency.** More replicas waiting on a
model is cheap; more concurrent requests per replica risks the event loop.

### Where the ceiling actually is

Not in the container. It is the model deployment's provisioned capacity — 25
units of `DataZoneStandard` by default. Scaling the app past what the model can
serve converts a slow platform into a rate-limited one.

---

## 4. Cost

Four things cost money, in this order:

1. **Model tokens.** Dominant. A tool-using turn costs at least twice a simple
   one: one call to decide, one to answer.
2. **Provisioned model capacity.** Billed on the SKU regardless of use.
3. **Telemetry.** Per GB ingested and retained. At `traceSampleRatio: 1` every
   request is traced, and this becomes real before inference does.
4. **Container Apps.** Only above the free grant; zero at `minReplicas: 0`.

### Bounding a turn

```dotenv
PLATFORM_AGENT__MAX_TOOL_INVOCATIONS=4
PLATFORM_AGENT__MAX_MODEL_CALLS=4
```

Checked *between* loop iterations, where stopping still saves the next call.

### Reading spend

```kusto
AppTraces
| where Message has "llm.call_completed"
| extend Tokens = toint(Properties["prompt_tokens"]) + toint(Properties["completion_tokens"])
| summarize Tokens = sum(Tokens), Calls = count() by bin(TimeGenerated, 1h)
| render timechart
```

**Cost reports zero until rates are configured.** Deliberate: a fabricated figure
that reaches a dashboard is worse than a missing one, because nobody
investigates a number that looks right.

```dotenv
PLATFORM_AZURE_FOUNDRY__INPUT_COST_PER_MILLION_TOKENS=0.15
PLATFORM_AZURE_FOUNDRY__OUTPUT_COST_PER_MILLION_TOKENS=0.60
```

---

## 5. Reliability controls

Three layers, applied in order, each for a different failure.

**Timeouts** bound a single call. `model_call_seconds` defaults to 60; the
cold-start budget is separate and generous, because an instance start takes tens
of seconds and a tight timeout makes every cold start look like an outage.

**Retry** handles a transient failure — three attempts, exponential backoff with
full jitter. Never applied to streaming: a partially delivered answer cannot be
replayed.

**The circuit breaker** handles a provider that is actually down. After five
consecutive counted failures it stops calling for 30 seconds, then allows one
trial request.

Retry and the breaker solve opposite problems. Retry assumes trying again is
cheap; when a provider is down, every request pays the full timeout three times
and the retries become load on something already struggling. The breaker turns
that into an immediate, cheap failure.

**Validation failures never open the breaker.** They are the caller's fault, and
a stream of malformed requests must not cut off a healthy provider for everyone.

```bash
# Is a breaker open right now?
az containerapp logs show -n <backend-app> -g <rg> --tail 200 \
  | grep llm.circuit_open
```

Tuning:

```dotenv
PLATFORM_LLM_GATEWAY__CIRCUIT_BREAKER__ENABLED=true
PLATFORM_LLM_GATEWAY__CIRCUIT_BREAKER__FAILURE_THRESHOLD=5
PLATFORM_LLM_GATEWAY__CIRCUIT_BREAKER__RESET_TIMEOUT_SECONDS=30
```

With a single provider and no fallback, an open breaker means certain failure
rather than unlikely success. A deployment in that position may reasonably
disable it — that is why the switch exists.

---

## 6. Alerts

Six rules, in `infra/bicep/modules/alerts.bicep`. Off outside staging and
production: a channel that pages during development gets muted, and it is the
same channel production uses.

| Rule | Severity | Fires when |
| --- | --- | --- |
| Backend unreachable | 1 | No successful readiness request in 15 minutes |
| Request failures | 1 | More than 5 5xx responses in 5 minutes |
| Circuit breaker opened | 2 | The gateway stopped calling a provider |
| Latency degraded | 2 | P95 chat latency above threshold for 10 minutes |
| Token spend | 2 | Hourly tokens above threshold |
| Container restarts | 3 | More than 3 restarts in an hour |

4xx is excluded from the failure rule. A client sending bad requests is not an
outage, and alerting on it trains people to ignore the rule.

**Token spend is the only rule that fires when nothing is broken.** It is there
because the expensive failure is silent: a tool loop that will not settle
returns 200 for every request while spending real money.

Alerts create an action group only when an email is supplied. Without one the
rules exist and fire silently — visible in the portal, paging nobody. Check:

```bash
azd env get-value ALERTS_NOTIFY   # false means nobody is being told
```

---

## 7. Routine tasks

**Deploy** — see `ci-cd.md`. Manual, deliberately.

**Roll back** — a revision traffic switch, seconds. See `ci-cd.md`.

**Rotate the Tavily key** — regenerate at tavily.com, then:
```bash
azd env set TAVILY_API_KEY tvly-...
azd provision
```
Azure needs no key rotation at all: `disableLocalAuth: true` means there is none.

**Change the model** — three environment variables and a provision. Nothing in
the source names a model.

**Change a prompt** — edit the asset under `prompts/`, bump its version, deploy.
Prompts are loaded at startup, so this needs a new revision, not a restart.

---

## 8. What is not covered

- **Load testing.** The baseline above is single-threaded latency, not
  throughput under concurrency. Nothing here has been load tested.
- **Backup.** No component holds persistent data yet — see `backup-recovery.md`.
- **Multi-region, DR automation, global traffic management.** Out of scope.
