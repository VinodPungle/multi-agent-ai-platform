# Incident response

For someone woken at 03:00 who did not build this. Every command is
copy-pasteable and no step assumes context.

---

## 0. First two minutes

```bash
BACKEND=$(azd env get-value SERVICE_BACKEND_URI)

curl -s -o /dev/null -w "%{http_code}\n" "$BACKEND/ready"
curl -s "$BACKEND/health" | python -m json.tool
```

| Result | Go to |
| --- | --- |
| Connection refused / timeout | [§1 Unreachable](#1-the-platform-is-unreachable) |
| 503 | [§2 Not ready](#2-ready-returns-503) |
| 200, users still failing | [§3 Requests failing](#3-requests-are-failing) |
| 200, users say it is slow | [§4 Slow](#4-everything-is-slow) |
| 200, answers are wrong or empty | [§5 Bad answers](#5-answers-are-wrong-or-empty) |

**Get the correlation ID first if a user reported it.** Every request carries
one, returned in `X-Correlation-ID` and present on every log record and span. It
gives you that user's exact server-side history and turns a vague report into a
single query:

```kusto
AppTraces | where Properties["correlation_id"] == "<id>" | order by TimeGenerated asc
```

---

## 1. The platform is unreachable

**Impact:** total outage.

```bash
az containerapp replica list -n <backend-app> -g <rg> -o table
az containerapp revision list -n <backend-app> -g <rg> -o table
```

**No replicas, `minReplicas: 0`** — scale-to-zero. The next request wakes it.
Not an incident in development; in production `minReplicas` should be 1, so
check whether it was changed.

**Replicas restarting repeatedly** — a crash loop:

```bash
az containerapp logs show -n <backend-app> -g <rg> --tail 200
```

The most common cause is configuration the platform validates at startup and
refuses on purpose: `debug=true` in production, a wildcard CORS origin, or the
mock provider in a production-like environment. These are deliberate refusals,
and the log line names the field.

**A recent deployment** — roll back first, diagnose after:

```bash
az containerapp revision list -n <backend-app> -g <rg> -o table
az containerapp ingress traffic set -n <backend-app> -g <rg> \
  --revision-weight <last-good-revision>=100
```

---

## 2. `/ready` returns 503

Readiness fails when a component reports unhealthy. The body says which.

```bash
curl -s "$BACKEND/health" | python -m json.tool
```

**`file-prompts` unhealthy, zero assets** — the container cannot find
`prompts/`. Every agent turn resolves a prompt, so nothing can be served. Check
that the image contains `/app/prompts`; the detail line names the directory it
searched.

**A provider unhealthy** — it reports *configuration*, so unhealthy means
misconfigured, not unreachable. Check endpoint and deployment name. A 404 here
is almost always the model name used where the *deployment* name belongs.

**`session-memory` unhealthy** — the conversation store is full. It is bounded
deliberately; a restart clears it and loses history.

---

## 3. Requests are failing

```kusto
AppRequests
| where TimeGenerated > ago(30m) and toint(ResultCode) >= 500
| summarize Failures = count() by ResultCode, Url
| order by Failures desc
```

Then find the category:

```kusto
AppTraces
| where TimeGenerated > ago(30m) and Message has "llm.call_failed"
| extend Category = tostring(Properties["error_category"])
| summarize count() by Category
```

| Category | Meaning | Action |
| --- | --- | --- |
| `provider` | The model rejected or failed the call | §3.1 |
| `timeout` | It did not answer in budget | §4 |
| `network` | It could not be reached | §3.1 |
| `validation` | The request was bad | Client-side; not an outage |
| `policy_violation` | A budget was exceeded | Expected; check the limits |

### 3.1 Provider failures

**Is the circuit breaker open?**

```bash
az containerapp logs show -n <backend-app> -g <rg> --tail 500 | grep llm.circuit_open
```

If it is, the gateway has stopped calling that provider after five consecutive
failures. Users are getting fast failures instead of slow ones — better, but
still failures. It retries automatically every 30 seconds.

**Check the provider itself:**

```bash
az cognitiveservices account show -n <resource> -g <rg> --query properties.provisioningState
az cognitiveservices account deployment list -n <resource> -g <rg> -o table
```

Common causes, in the order they actually occur:

- **429** — model capacity exceeded. Raise deployment capacity or lower
  concurrency. This is the most likely cause of a sudden failure under load.
- **401** — the managed identity lost its role, or an identity change did not
  propagate. Check `Cognitive Services User` on the account.
- **400** — a request-shape mismatch, usually after a model change. Reasoning
  models reject `max_tokens` and need `max_completion_tokens`; that setting is
  `PLATFORM_AZURE_FOUNDRY__OUTPUT_TOKEN_PARAMETER`.

**Mitigation while you investigate:** switch the agent to the mock provider to
restore *a* response, or accept the outage. Note the platform refuses the mock
in production-like environments, so this means changing
`PLATFORM_APP__ENVIRONMENT` too — which disables other production protections.
Usually the wrong trade; prefer rolling back or fixing the provider.

---

## 4. Everything is slow

```kusto
AppRequests
| where TimeGenerated > ago(1h) and Url has "/api/v1/chat"
| summarize p50 = percentile(DurationMs, 50), p95 = percentile(DurationMs, 95) by bin(TimeGenerated, 5m)
| render timechart
```

**Is it the model or the platform?**

```kusto
AppTraces
| where TimeGenerated > ago(1h) and Message has "llm.call_completed"
| summarize p95_model_ms = percentile(todouble(Properties["latency_ms"]), 95)
```

If model latency accounts for nearly all request duration, the platform is fine
and the model is slow. The platform's own overhead is single-digit
milliseconds — see `operations.md`.

**Expected slowness, not an incident:**

- **A searching turn takes 15–20 seconds.** Two model calls plus a search. If
  users are complaining about *those* specifically, that is the design.
- **The first request after idle** in an environment with `minReplicas: 0`.
- **A cold Managed Compute deployment**, tens of seconds.

**Actual causes:**

- **Capacity exhaustion** — requests queue behind the model. Check for 429s.
- **Too few replicas** — check `RestartCount` and replica count.
- **A tool loop not settling** — check `model_calls` per turn; the budget should
  cap it at 4.

---

## 5. Answers are wrong or empty

**Empty answer, `finish_reason: length`** — the output cap was consumed before
any visible text. Reasoning models spend tokens thinking, and a cap below ~200
returns nothing usable. Raise `PLATFORM_AZURE_FOUNDRY__MAX_OUTPUT_TOKENS`.

**Answers ignore the conversation** — session memory is in-process. It does not
survive a restart and is *not shared between replicas*, so with more than one
replica a user's turns can land on different instances and lose history. This is
a known limitation, not a bug to hunt.

**Answers are stale and no search happened** — whether to search is the model's
judgement. Check for a `tool` event; if the model never called the tool, the
prompt biased it wrongly for that question. Not a failure to fix at 03:00.

**Search returns nothing useful** — check which provider is configured.
DuckDuckGo returns encyclopaedic abstracts, not ranked pages, and is weak on
current events by design.

---

## 6. Escalation

| Situation | Action |
| --- | --- |
| Outage over 15 minutes with no diagnosis | Roll back to the last known-good revision. Diagnose from logs afterwards |
| Provider outage with no fix | Azure support. There is no failover — a known limitation |
| Cost anomaly | Scale to zero or disable the agent. Money spent is not recoverable |
| Suspected credential compromise | See §7 |

Rolling back is nearly free here: a traffic switch, seconds, no rebuild. Prefer
it over debugging in production.

---

## 7. Suspected compromise

**Azure has no key to revoke** — `disableLocalAuth: true`. To cut access,
remove the managed identity's role assignment:

```bash
az role assignment delete --assignee <principal-id> --scope <foundry-account-id>
```

That stops all inference immediately, including legitimate traffic. It is the
right first move if you believe the identity is compromised.

**Tavily** — regenerate at tavily.com, then `azd env set TAVILY_API_KEY` and
`azd provision`.

**Then check what was actually accessed:**

```kusto
AppTraces
| where TimeGenerated > ago(24h) and Message has "llm.call_completed"
| summarize Calls = count(), Tokens = sum(toint(Properties["completion_tokens"]))
    by bin(TimeGenerated, 1h)
```

---

## 8. After the incident

Write down what happened, what was tried, and what actually fixed it. If a
runbook step was wrong or missing, fix this file in the same change — the moment
you know is the only moment that knowledge is cheap to capture.

If a defect caused it, it needs a test that would have caught it. This project's
consistent lesson is that the defects reaching production are the ones where a
local approximation agreed with us and a real system did not.
