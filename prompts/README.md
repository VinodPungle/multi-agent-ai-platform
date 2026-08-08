# Prompts

Prompts are **versioned assets**, never string literals in Python
(`CLAUDE.md`, "Prompt Management"; `architecture.md` §34, §72).

```
prompts/
├── agents/
│   ├── chat/
│   ├── coding/
│   ├── planner/
│   └── research/
├── evaluation/
├── shared/
└── system/
```

## Why they live outside the source tree

Treating a prompt as data rather than code is what later makes prompt
versioning, A/B testing, evaluation and rollback possible **without a code
deployment**. A prompt embedded in a Python file can only be changed by shipping
a release.

Agents never read these files directly. They resolve a prompt by id and version
through `PromptProvider`, so the backing store can move from the filesystem to a
database or a prompt marketplace without any agent changing.

## Not yet populated

Milestone 01 registers no agents, so there is no prompt to write. Assets arrive
in Milestone 03 with the chat agent.

## Required metadata

Every prompt file carries front matter, mirroring
`agent_platform_sdk.dto.prompt.PromptAsset`:

```yaml
---
prompt_id: chat-agent-system
version: '1.0'
owner: platform-team
description: System prompt for the general conversational agent.
variables:
  - name: user_locale
    description: BCP 47 locale for the response.
    required: true
compatible_models:
  - fw-kimi-k3
  - claude-sonnet-5
updated_at: 2026-01-01T00:00:00Z
---
```

## Rules

1. **Version, never overwrite.** An agent may pin a version for reproducibility.
   Editing a published version silently changes the behaviour of everything
   pinned to it.
2. **Declare every variable.** The registry validates that a caller supplied
   what the template expects, so a missing variable fails at render time with a
   clear message rather than reaching a model as the literal text `{user_input}`.
3. **No secrets, no customer data.** Prompts are committed to source control.
4. **Record compatible models.** A prompt tuned for one model's instruction
   format frequently degrades on another.
