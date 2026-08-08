# `agent_platform_sdk`

The platform's **public contract surface**. Everything here is an interface, a data
contract, or a policy — never an implementation.

```
agent_platform (backend)  ->  agent_platform_sdk  ->  agent_platform_shared
```

## Structure

| Package | Responsibility |
| --- | --- |
| `interfaces/` | Provider, gateway and registry protocols (`LLMGateway`, `LLMProvider`, `MemoryProvider`, `ToolProvider`, …) |
| `contracts/` | Cross-cutting contracts such as `ExecutionContext` and health reporting |
| `dto/` | Data transfer objects exchanged across process and layer boundaries |
| `events/` | Runtime event definitions published during execution |
| `policies/` | Budget, retry and timeout policy models |
| `schemas/` | JSON-Schema helpers for tool input/output declarations |
| `types/` | Shared enums and type aliases |

## Rules

1. **No implementations.** Concrete providers live in `agent_platform.providers`.
2. **No provider SDKs.** This package must never import `openai`, `anthropic`,
   `azure-*`, `langchain`, or any other vendor library. Adding one would leak
   infrastructure into the contract layer.
3. **No web framework.** `fastapi`, `starlette` and friends belong to the
   presentation layer.
4. **Pydantic and the standard library only.**
5. **Never duplicate an interface.** If both the backend and a future service need
   a contract, it belongs here — not copied into both.

Interfaces are declared with `typing.Protocol` and `@runtime_checkable` so that
implementations do not need to inherit from platform base classes. This keeps
providers structurally typed and independently testable.

See [ADR-0004](../../docs/adr/0004-provider-abstraction-via-protocols.md).

## Which contract business logic depends on

`LLMGateway`, not `LLMProvider`. The gateway is the single path to model
inference; `LLMProvider` is infrastructure-facing and named only by the gateway
and the composition root. The distinction is what keeps retry, timeout,
telemetry and cost handling out of orchestration.

See [ADR-0006](../../docs/adr/0006-llm-gateway-and-provider-neutral-contract.md).
