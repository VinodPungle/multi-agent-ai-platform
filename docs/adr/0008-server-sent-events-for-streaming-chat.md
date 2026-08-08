# ADR-0008: Stream chat over server-sent events, consumed with `fetch`

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 02 — Chat UI and Session Memory

## Context

A chat turn produces text incrementally over seconds. Delivering it only when
complete makes a fast model feel slow and a slow one feel broken, so the
transport is a product decision as much as a technical one.

Three questions had to be answered together, because the answer to each
constrains the others: what protocol carries the tokens, what the client uses to
read it, and how a failure that happens *after* the response has started is
reported.

## Decision

### Server-sent events, not WebSockets

The traffic is one-way and request-scoped: the client sends one prompt and
receives one answer. SSE is exactly that shape, and because it rides on plain
HTTP it inherits everything already built — correlation middleware, the error
envelope, CORS, health checks, proxies, load balancers, and the container's
existing port.

A WebSocket would buy bidirectionality that a request-response turn never uses,
and would cost a parallel implementation of all of the above.

### `POST`, consumed with `fetch` — not `EventSource`

`EventSource` is the browser's built-in SSE client and is unusable here for two
independent reasons:

1. It only issues `GET` and cannot send a body. A prompt would have to travel in
   a query string, which proxies log, browsers cap in length, and history
   retains.
2. It reconnects automatically and cannot be cancelled cleanly. Both are wrong
   for a chat turn: a silent reconnect re-runs a generation the user has already
   paid for, and "stop generating" needs cancellation that actually stops it.

`fetch` with a `ReadableStream` gives a POST body, real cancellation through
`AbortSignal`, and no reconnection. The cost is parsing SSE frames by hand —
about thirty lines, and the buffering that parser needs is the subject of nine
tests, because a parser that assumes each network chunk contains whole frames
works locally and drops events in production.

### Failures after the first byte are reported in-band

Once a `StreamingResponse` exists, the 200 and the SSE headers are committed and
the status code can no longer carry a failure. So the contract has two failure
paths, and which one applies is decided by *when*:

| When | How it is reported |
| --- | --- |
| Before the stream opens — empty prompt, no provider | HTTP status, standard error envelope |
| After the first byte — provider died mid-generation | An `error` event on the stream |

This forced a specific shape on the service. `ChatService.stream()` is an
`async def` that *returns* an iterator rather than an async generator that
yields one, because a generator body does not run until first iterated — which
is after the response has been committed. Validation inside the generator would
therefore reject a request the client has already been told succeeded. The
integration test that caught this is `test_an_invalid_message_fails_before_the_stream_opens`.

### Stopping keeps the partial answer

Cancelling the request closes the connection; the backend sees a disconnect,
stops generating, and stores what was produced. The user keeps the text they
already read, and the conversation history matches what was on screen.

Discarding it was the alternative and is worse: a history that omits what the
user demonstrably saw is more confusing than one that ends mid-sentence.

### Discriminated event types, not one event with optional fields

`started`, `delta`, `completed`, `error` — four types with a `type`
discriminant, mirrored by a Zod discriminated union in the client. A single
event model would need every field nullable and a consumer would have to know by
convention which fields are populated when.

`completed` re-sends the full content even though the deltas already carry it.
Deliberate redundancy: a client that dropped a frame self-corrects instead of
displaying a silently truncated answer.

## Alternatives Considered

### WebSockets

**Rejected because:** bidirectionality is unused, and it needs its own auth,
correlation, error handling and proxy configuration. Revisit if a genuinely
bidirectional feature arrives — live collaboration, or interrupting a running
agent with new instructions.

### Long polling

**Rejected because:** it delivers the answer in chunks, not tokens, and each
poll pays a full request round trip. It is the fallback for environments without
SSE; none of the supported browsers is one.

### `EventSource` with the prompt in a query string

**Rejected because:** prompts are user content and can be long. Query strings
are logged by every proxy in the path, capped at a few kilobytes, and retained
in browser history.

### Buffering the whole answer and returning JSON

Simplest by far, and the non-streaming endpoint does exactly this — it is kept
for integrations that cannot consume a stream.

**Rejected as the default because:** the perceived-latency difference is the
feature. It also removes any possibility of a stop button, since there is
nothing to stop.

## Consequences

### Positive

- Streaming works over the existing HTTP stack with no new infrastructure.
- Cancellation is real: stopping closes the connection and the backend stops.
- The SSE layer is provider-independent. It encodes domain events, and knows
  nothing about which provider produced them.
- The same `ChatService` is driven by both endpoints, so the streamed and
  non-streamed paths cannot drift.

### Negative

- SSE frame parsing is ours to maintain. It is small, but it is protocol code,
  and the chunk-boundary cases are not obvious.
- `X-Accel-Buffering: no` is required for nginx, and its absence produces a
  stream that works locally and arrives in one block once deployed — a failure
  mode with a misleading symptom.
- Reconnection is not implemented. A dropped connection mid-generation loses the
  remainder of that answer; the partial text is kept and the user can regenerate.
- A mid-stream failure returns HTTP 200. Anything monitoring status codes alone
  will not see it — the `llm.call_failed` and `chat.turn_failed` log events are
  what carry it.

### Neutral

- `ChatStartedEvent` carries no `provider_id`. The gateway resolves the provider
  when the first chunk is requested, which is after this event must be sent;
  publishing an empty string would put a field on the wire that is always wrong.
  Attribution lives on the non-streaming response and in telemetry.

## Compliance

- `tests/unit/api/test_sse.py` pins the framing rules, including that a newline
  inside a payload cannot break a frame and that the buffering headers are set.
- `src/frontend/src/api/chat.test.ts` covers chunk boundaries falling mid-frame,
  mid-line and mid-UTF-8-sequence.
- `tests/integration/api/test_chat_endpoints.py` parses real SSE bytes with a
  real parser rather than searching the response text, so a stream no client
  could read fails the suite.
- `src/frontend/src/features/chat/ChatPage.test.tsx` asserts the user-visible
  behaviour: streamed text renders, a mid-stream failure appears beside the
  partial answer, and stop leaves what was generated on screen.

## References

- `docs/milestones/milestone-02-chat-ui-session-memory.md`
- `architecture.md` §24 — Response Streaming; §50 — Streaming Lifecycle
- [ADR-0006](./0006-llm-gateway-and-provider-neutral-contract.md) — the gateway this streams through
