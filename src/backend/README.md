# `agent_platform` (backend)

FastAPI presentation layer and agent runtime for the Enterprise Multi-Agent AI Platform.

## Package layout

The layout follows `architecture.md` §68. Every package owns a single responsibility.
Milestone 01 creates the full skeleton so later milestones add files rather than
restructure the tree.

| Package | Responsibility | Milestone 01 status |
| --- | --- | --- |
| `api/` | HTTP surface: routers, middleware, error handlers. No business logic. | Implemented (health only) |
| `configuration/` | Strongly typed settings, validated once at startup | Implemented |
| `telemetry/` | structlog and OpenTelemetry bootstrap | Implemented |
| `dependencies/` | Composition root — the `dependency-injector` container | Implemented |
| `exceptions/` | Platform exception hierarchy | Implemented |
| `application/` | Use cases and orchestration services | Skeleton |
| `domain/` | Domain models and business rules. Depends on nothing. | Skeleton |
| `runtime/` | Agent Runtime — request lifecycle, execution, policy enforcement | Skeleton |
| `workflow/` | LangGraph workflow construction and execution | Skeleton |
| `agents/` | Specialised agents (chat, research, coding, …) | Skeleton |
| `providers/` | Infrastructure implementations of SDK provider interfaces | Skeleton |
| `registries/` | Agent, model, provider, tool, prompt, memory registries | Skeleton |
| `factories/` | Factories that resolve implementations through registries | Skeleton |
| `memory/` | Conversation and long-term memory implementations | Skeleton |
| `tools/` | Tool implementations | Skeleton |
| `prompts/` | Prompt loading and rendering (assets live in `/prompts`) | Skeleton |
| `evaluation/` | Execution telemetry, cost and quality capture | Skeleton |
| `security/` | Credential resolution, authentication, authorisation | Skeleton |
| `storage/` | Persistence adapters | Skeleton |
| `events/` | Runtime event publication | Skeleton |
| `models/` | Model catalogue types | Skeleton |
| `utils/` | Narrow helpers with no better home | Skeleton |

Skeleton packages contain a module docstring stating their responsibility and the
milestone that fills them in. They are real importable packages so the dependency
direction is enforced from day one.

## Dependency rule

```
api  ->  application  ->  domain
              |
              v
     sdk interfaces (agent_platform_sdk)
              ^
              |
        providers / storage / security   (implementations, injected at runtime)
```

`domain` and `application` must never import `providers`, `storage`, `security`, or
any vendor SDK. Implementations are supplied through the container in
`dependencies/container.py`.

## Running locally

From the repository root:

```bash
uv run agent-platform            # or: uv run uvicorn agent_platform.api.app:create_app --factory
```

See [`docs/developer-setup.md`](../../docs/developer-setup.md).
