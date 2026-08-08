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

## Current surface (Milestone 02)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/live` | Liveness. Touches no dependency. |
| `GET` | `/ready` | Readiness. 503 when a component is unhealthy. |
| `GET` | `/health` | Per-component status and probe latency. Always 200. |
| `GET` | `/api/v1/info` | Build identity and effective feature flags. |
| `POST` | `/api/v1/chat/messages` | One turn, complete answer. |
| `POST` | `/api/v1/chat/messages/stream` | One turn, streamed as SSE. |
| `POST` | `/api/v1/chat/conversations/{id}/regenerate` | Re-answer the last message, streamed. |
| `GET` | `/api/v1/chat/conversations/{id}` | Stored history. Empty for an unknown id. |
| `DELETE` | `/api/v1/chat/conversations/{id}` | Forget a conversation. Always 204. |

Health probes sit at the application root rather than under `/api/v1`: they are
infrastructure concerns and must not move when the API is versioned.

## Streaming

The streaming endpoints return `text/event-stream`. Four event types, discriminated
on `type`:

| Event | When | Carries |
| --- | --- | --- |
| `started` | Once, before any text | `conversation_id`, `message_id`, `model_id` |
| `delta` | Per increment | `delta` — append it, never replace |
| `completed` | Terminal, on success | Full `content`, `usage`, `finish_reason`, `latency_ms` |
| `error` | Terminal, on failure | `category`, `message`, `correlation_id` |

```
curl -N -X POST http://localhost:8000/api/v1/chat/messages/stream \
  -H 'Content-Type: application/json' \
  -d '{"message": "Explain server-sent events"}'
```

Three properties a client depends on:

- **Deltas concatenate to `content` exactly.** No delta repeats text already sent.
- **A failure after the first byte arrives as an `error` event, not a status
  code.** The 200 is already committed by then. A failure *before* the stream
  opens — an empty message, no provider registered — is a normal status code with
  the standard error envelope.
- **Closing the connection stops generation** and keeps the partial answer in
  history, so what the user read is what the conversation contains.

`started` deliberately carries no `provider_id`: the gateway resolves a provider
when the first chunk is requested, which is after this event must be sent.
Attribution is on the non-streaming response and in telemetry. See
[ADR-0008](../adr/0008-server-sent-events-for-streaming-chat.md).

Conversation identifiers are issued by the server. Omit `conversation_id` to
start a new conversation and read it from the response or the `started` event.

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

Not committed yet: it would be a second copy of something already generated, and
a second copy is a copy that goes stale. Publishing a versioned snapshot becomes
worthwhile once external consumers depend on the contract (Milestone 07).

The SSE endpoints appear in the schema with a `text/event-stream` response, but
OpenAPI cannot express the event sequence — that contract is documented above and
enforced by tests, not by the schema.
