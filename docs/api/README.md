# API documentation

The OpenAPI document is **generated, never hand-written** (`CLAUDE.md`, "API
Documentation"). FastAPI derives it from the Pydantic models and route
signatures, so it cannot drift from the implementation.

## Where to find it

With `PLATFORM_APP__DEBUG=true` (the default in development):

| | |
| --- | --- |
| Swagger UI | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| Raw schema | <http://localhost:8000/openapi.json> |

All three are **withdrawn when debug is off**. In a production-like environment
they describe the attack surface, so they are disabled along with debug mode and
the configuration validator refuses to start with `debug=true` there.

## Current surface (Milestone 01)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/live` | Liveness. Touches no dependency. |
| `GET` | `/ready` | Readiness. 503 when a component is unhealthy. |
| `GET` | `/health` | Per-component status and probe latency. Always 200. |
| `GET` | `/api/v1/info` | Build identity and effective feature flags. |

Health probes sit at the application root rather than under `/api/v1`: they are
infrastructure concerns and must not move when the API is versioned.

## Error envelope

Every failing endpoint returns the same shape, so a client needs one parser:

```json
{
  "error": {
    "category": "validation",
    "message": "Request validation failed",
    "correlation_id": "5e2f8c1a-...",
    "fields": [{ "location": "body.temperature", "message": "less than or equal to 2" }]
  }
}
```

`category` is a normalised `ErrorCategory` and determines the HTTP status, so
adding an exception type never changes the handler. `correlation_id` matches the
`X-Correlation-ID` response header and is what turns a user's report into a
searchable server-side trace.

Stack traces and internal detail are never returned. Full diagnostics are logged
server-side against the same correlation ID.

## Conventions

- Every public API is versioned: `/api/v1/...`.
- One router per feature (`chat`, `agents`, `models`, `tools`).
- Requests and responses are Pydantic models, so validation and documentation
  come from one declaration.
- No internal implementation detail is exposed.

## Exporting the schema

```bash
curl http://localhost:8000/openapi.json > docs/api/openapi.json
```

Not committed in Milestone 01: with four endpoints it would be a second copy of
something already generated, and a second copy is a copy that goes stale.
Publishing a versioned snapshot becomes worthwhile once external consumers
depend on the contract (Milestone 07).
