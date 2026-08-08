# `agent_platform_shared`

Cross-cutting **runtime utilities** shared by every Python service in the platform.

This package sits at the bottom of the dependency graph:

```
agent_platform (backend)  ->  agent_platform_sdk  ->  agent_platform_shared
```

## What belongs here

Mechanics with no business meaning and no external dependencies:

| Module | Responsibility |
| --- | --- |
| `correlation.py` | Ambient correlation / request identifiers carried across `await` boundaries via `contextvars` |
| `identifiers.py` | Generation of correlation, request and execution identifiers |
| `clock.py` | `Clock` protocol and a UTC system implementation, so time is injectable in tests |

## What does not belong here

- Domain concepts, DTOs or provider interfaces — those live in `agent_platform_sdk`.
- Anything that imports a third-party package. This package is **standard library only**
  by design: every dependency added here is imposed on every service that imports it.

## Why it is separate from the SDK

The SDK is a *contract* surface that outside consumers compile against and that we
version carefully. These utilities are implementation mechanics that the SDK itself
needs. Keeping them apart stops the contract surface from acquiring runtime concerns.

See [ADR-0003](../../docs/adr/0003-workspace-layout-and-package-boundaries.md).
