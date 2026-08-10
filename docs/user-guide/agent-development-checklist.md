# Agent development checklist

Work through this in order. Everything above the line is design; nothing below it
should start until the design section is complete, because every item below
assumes an answer from above.

Running example: **Internal Fitments** ([reference](./internal-fitments-reference.md)).

---

## Design

- [ ] **Business objective defined.** One sentence, in the sponsor's language.
      *"Get a candidate through internal fitment without anyone chasing status."*
- [ ] **Business process drawn**, including where work waits and what someone has
      to *remember* to do
- [ ] **Business states identified**, with the transition that causes each one
- [ ] **Every decision listed**, and marked automated, human, or **manual by
      design** — the third category is what stops the tool's boundary drifting
- [ ] **Human accountability named** for each human decision
- [ ] **Agent boundaries justified** — each passes ≥2 criteria from the
      [design guide §3](./agent-design-guide.md#3-when-to-create-an-agent)
- [ ] **No agent exists solely because its prompt differs**
- [ ] **Agent contract written** for each: purpose, responsibility, *what it is
      not responsible for*, inputs, outputs, completion criteria, error states
- [ ] **System of record decided.** Not conversation memory
- [ ] **Side effects listed**, each with an owner agent and an idempotency strategy
- [ ] **Cross-cutting side effects centralised** (one door to Slack/email)
- [ ] **Model selected per agent** on capability, context, latency and cost — not
      by name
- [ ] **Evaluation criteria written** — before any agent is built
- [ ] **Human baseline measured** — what does agreement between two experts look like?

---

## Build

### Prompt

- [ ] Lives under `prompts/` as a `.md` file with front matter, never in Python
      (convention: `prompts/agents/<name>/system.md`; the loader keys on
      `prompt_id`, not the path)
- [ ] Front matter complete: `prompt_id`, `version`, `owner`, `description`,
      `variables`, `compatible_models`, `updated_at`
- [ ] States when to use each tool and when not to
- [ ] States what the agent must never do
- [ ] Version **pinned** on the descriptor if the agent's output is evaluated

### Descriptor

- [ ] Settings block follows `ResearchAgentSettings`, with
      `Annotated[tuple[str, ...], NoDecode]` on `tool_ids`
- [ ] Empty `provider_id`/`model_id` inherit the primary agent's
- [ ] `temperature` set deliberately — `None` means the provider's default, and
      **0 is a real value**, not "unset"
- [ ] `tool_ids` lists only what this agent may reach
- [ ] `BudgetPolicy` set — `max_tool_invocations`, `max_model_calls` at minimum
- [ ] `TimeoutPolicy` reflects the real work, not the default
- [ ] Registered in `build_agent_registry()`
- [ ] Startup validation passes — no agent names a model nothing serves

### Tools

For each, the full list is in the
[tool guide §9](./tool-development-guide.md#9-checklist). The ones people miss:

- [ ] `description` says **when** to use it and **what comes back**
- [ ] `input_schema` bounded — `maxItems`, `maxLength`, `pattern` — **and every
      bound re-checked in `validate()`**, which raises `ValidationError`. The
      schema is sent to the model; only MCP tools have it enforced
- [ ] `execute` never raises; every path returns a `ToolResult`
- [ ] `error_message` safe for a model and an operator — no stack traces, no
      upstream response bodies
- [ ] Every log line carries `**context.to_log_fields()`, with nothing passed
      twice
- [ ] **Writes carry an idempotency key derived from business identity**
- [ ] Writes produce a business audit record
- [ ] Retry is off unless the operation is idempotent
- [ ] `health_check` is cheap and costs nothing
- [ ] Registered in `build_tool_registry()`

### Wiring

- [ ] No business logic imports a provider SDK
- [ ] No model, endpoint or deployment name appears in source
- [ ] Nothing instantiates infrastructure inside business logic — inject it
- [ ] Human gates are a terminal state plus a separate trigger — **no turn is
      held open**
- [ ] Scheduled work is driven by an external trigger calling your API
- [ ] Configuration added to `.env.example` (a test asserts it matches the
      settings model)
- [ ] Configuration added to `infra/bicep/main.parameters.json` if Azure must set
      it — **a missing parameter silently takes its Bicep default**

---

## Test

- [ ] Unit tests for your own logic — scoring, SLA arithmetic, state transitions
- [ ] Tool tests: happy path, invalid arguments, upstream failure, timeout
- [ ] **Replay test: two calls, one idempotency key → one side effect**
- [ ] Secret tests assert absence *and* that the assertion can fail — a test that
      greps empty output proves nothing
- [ ] Doubles shaped to the **real** contract, not to your code
- [ ] Integration test: API in, answer out, against a stub provider
- [ ] End-to-end: one record through both human gates
- [ ] Failure scenarios: interviewer unavailable, invite declined, SLA breached,
      transcript missing, duplicate notification, portal update fails, retry of
      an already-completed action
- [ ] **At least one real call made against the real provider**

---

## Evaluate

- [ ] Golden dataset curated by domain experts, anonymised
- [ ] Hard cases and **unanswerable** cases both included
- [ ] Harness runs through the `AgentRuntime`, not the gateway
- [ ] Candidate models compared on the same set, against cost and latency
- [ ] Override rate and time-to-decision instrumented at every gate

---

## Operate

- [ ] Model pricing configured — `PLATFORM_AZURE_FOUNDRY__INPUT_COST_PER_MILLION_TOKENS`,
      `..._OUTPUT_COST_PER_MILLION_TOKENS`, `PLATFORM_AZURE_FOUNDRY__PRICING_CURRENCY`
      — or every cost reads as zero. (The short `INPUT_COST_PER_MILLION_TOKENS`
      form is an **azd parameter**, not a runtime variable; in `.env` it is
      silently ignored.) Rates are per *provider*, not per model
- [ ] `/health` reports every component you added
- [ ] Business events logged beyond the platform's own: state transitions with
      actor and timestamp, gate decisions, SLA breaches, duplicate attempts
- [ ] Correlation id flows from your API through to the model call
- [ ] Alert on scope leakage — **it must be zero**
- [ ] Runbook entry: what to do when this agent misbehaves

---

## Security

- [ ] Authorisation enforced **in front of** the platform. Prompts are not access
      controls, and `required_permissions` is not enforced
- [ ] No PII in prompts, tool descriptions or log fields
- [ ] Untrusted business content (CVs, transcripts) treated as untrusted input
      into the model's context
- [ ] Secrets in Key Vault; nothing in source, images or config files
- [ ] Data retention decided and implemented in your state store
- [ ] The cost endpoint protected — spend by model and agent is commercially
      sensitive, and it is currently as open as the rest of the API

---

## Ship

- [ ] `task check` clean — `format:check` (black, prettier), `lint` (ruff check,
      eslint), `typecheck` (mypy --strict, tsc), `test` (pytest, vitest)
- [ ] **`uv run ruff format --check .` clean.** CI runs it; `task check` and
      pre-commit do not. Both formatters run in CI and have deadlocked over one
      line before, which no single local check would have revealed
- [ ] Documentation updated
- [ ] ADR written for any decision expensive to reverse
- [ ] Commit message explains **why**, not what
- [ ] Deployed with `azd deploy <service>` **separately**, and the running
      revision verified — a successful deploy report is not proof the new image
      is serving

---

## Definition of done

From `CLAUDE.md`, and it is a conjunction:

> Code builds · Tests pass · Lint passes · Type checking passes · Documentation
> updated · Logging implemented · Telemetry included · Configuration
> externalized · Security considered · Git commit message provided

If any item is missing, the task is incomplete.
