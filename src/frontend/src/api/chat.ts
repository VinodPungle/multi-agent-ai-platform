/**
 * Chat API contracts and the streaming client.
 *
 * Two reasons this does not use the browser's `EventSource`:
 *
 * 1. `EventSource` only issues `GET` and cannot send a body. Prompts belong in a
 *    body, not a query string — query strings are logged by proxies, capped in
 *    length, and end up in browser history.
 * 2. `EventSource` reconnects automatically and cannot be cancelled cleanly. For
 *    a chat turn both are wrong: a reconnect would silently re-run a generation
 *    the user already paid for, and "stop generating" needs cancellation to
 *    actually stop it.
 *
 * `fetch` with a `ReadableStream` gives a POST body, real cancellation through
 * `AbortSignal`, and no reconnection. The cost is parsing SSE frames ourselves,
 * which is about thirty lines.
 */

import { z } from 'zod';

import { ApiError, CORRELATION_ID_HEADER } from '@/api/client';
import { env } from '@/config/env';
import { errorResponseSchema } from '@/api/types';

/** Mirrors `agent_platform_sdk.types.enums.MessageRole`. */
export const messageRoleSchema = z.enum(['system', 'user', 'assistant', 'tool']);
export type MessageRole = z.infer<typeof messageRoleSchema>;

export const chatMessageSchema = z.object({
  role: messageRoleSchema,
  content: z.string(),
});
export type ChatMessage = z.infer<typeof chatMessageSchema>;

/** Response of `GET /api/v1/chat/conversations/{id}`. */
export const conversationSchema = z.object({
  conversation_id: z.string(),
  messages: z.array(chatMessageSchema),
});
export type Conversation = z.infer<typeof conversationSchema>;

// --- Streaming events -------------------------------------------------------
// One schema per event type, discriminated on `type`, mirroring
// `agent_platform.domain.chat`. Parsing every frame is deliberate: a malformed
// event is a contract break, and catching it here localises the failure to the
// boundary instead of letting `undefined` reach the renderer.

export const chatStartedEventSchema = z.object({
  type: z.literal('started'),
  conversation_id: z.string(),
  message_id: z.string(),
  model_id: z.string(),
});

export const chatToolEventSchema = z.object({
  type: z.literal('tool'),
  tool_id: z.string(),
  summary: z.string().optional().default(''),
});

export const chatDeltaEventSchema = z.object({
  type: z.literal('delta'),
  delta: z.string(),
});

export const chatCompletedEventSchema = z.object({
  type: z.literal('completed'),
  message_id: z.string(),
  content: z.string(),
  usage: z.object({ prompt_tokens: z.number(), completion_tokens: z.number() }),
  finish_reason: z.string().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
  cancelled: z.boolean().optional(),
});

export const chatErrorEventSchema = z.object({
  type: z.literal('error'),
  category: z.string(),
  message: z.string(),
  correlation_id: z.string().nullable().optional(),
});

export const chatStreamEventSchema = z.discriminatedUnion('type', [
  chatStartedEventSchema,
  chatToolEventSchema,
  chatDeltaEventSchema,
  chatCompletedEventSchema,
  chatErrorEventSchema,
]);

export type ChatStartedEvent = z.infer<typeof chatStartedEventSchema>;
export type ChatToolEvent = z.infer<typeof chatToolEventSchema>;
export type ChatDeltaEvent = z.infer<typeof chatDeltaEventSchema>;
export type ChatCompletedEvent = z.infer<typeof chatCompletedEventSchema>;
export type ChatErrorEvent = z.infer<typeof chatErrorEventSchema>;
export type ChatStreamEvent = z.infer<typeof chatStreamEventSchema>;

// --- SSE parsing ------------------------------------------------------------

/**
 * Turn a stream of decoded text into SSE events.
 *
 * A chunk boundary can fall anywhere — mid-frame, mid-line, mid-UTF-8 sequence.
 * The buffer is what makes that a non-issue: only whole frames, terminated by a
 * blank line, are ever parsed. Getting this wrong produces a client that works
 * against a fast local server and drops events against a real one.
 */
export async function* parseSseFrames(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<{ event: string; data: string }, void> {
  const reader = stream.getReader();
  // `stream: true` keeps a multi-byte character split across chunks intact.
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      if (signal?.aborted) {
        return;
      }

      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      let separator = buffer.indexOf('\n\n');
      while (separator !== -1) {
        const frame = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        separator = buffer.indexOf('\n\n');

        const parsed = parseFrame(frame);
        if (parsed) {
          yield parsed;
        }
      }
    }
  } finally {
    // Releasing the lock lets the body be cancelled by the caller's abort.
    reader.releaseLock();
  }
}

function parseFrame(frame: string): { event: string; data: string } | null {
  let event = 'message';
  const dataLines: string[] = [];

  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) {
      // A comment. Used to open the stream and to keep it alive.
      continue;
    }
    if (line.startsWith('event: ')) {
      event = line.slice('event: '.length);
    } else if (line.startsWith('data: ')) {
      dataLines.push(line.slice('data: '.length));
    }
  }

  return dataLines.length > 0 ? { event, data: dataLines.join('\n') } : null;
}

// --- Requests ---------------------------------------------------------------

export interface StreamChatOptions {
  message: string;
  conversationId?: string;
  signal?: AbortSignal;
}

async function toApiError(response: Response, correlationId: string): Promise<ApiError> {
  const headerCorrelationId = response.headers.get(CORRELATION_ID_HEADER) ?? correlationId;

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return new ApiError({
      message: `The server returned an unreadable response (HTTP ${response.status}).`,
      category: 'unexpected',
      status: response.status,
      correlationId: headerCorrelationId,
    });
  }

  const parsed = errorResponseSchema.safeParse(payload);
  if (!parsed.success) {
    return new ApiError({
      message: `The server returned an unexpected error format (HTTP ${response.status}).`,
      category: 'unexpected',
      status: response.status,
      correlationId: headerCorrelationId,
    });
  }

  return new ApiError({
    message: parsed.data.error.message,
    category: parsed.data.error.category,
    status: response.status,
    correlationId: parsed.data.error.correlation_id ?? headerCorrelationId,
    fields: parsed.data.error.fields,
  });
}

function newCorrelationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Open a chat stream and yield its events.
 *
 * Deliberately has **no timeout**. The shared `request()` helper applies one,
 * which is right for a request that should answer promptly and wrong for a
 * generation that legitimately runs for minutes. Cancellation is the caller's,
 * through `signal`.
 *
 * @throws {ApiError} if the request fails before the stream opens.
 */
export async function* streamChat(
  options: StreamChatOptions,
): AsyncGenerator<ChatStreamEvent, void> {
  yield* openStream('/api/v1/chat/messages/stream', {
    method: 'POST',
    body: JSON.stringify({
      message: options.message,
      ...(options.conversationId ? { conversation_id: options.conversationId } : {}),
    }),
    signal: options.signal,
  });
}

/** Re-answer the most recent message in a conversation. */
export async function* regenerateChat(
  conversationId: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent, void> {
  yield* openStream(`/api/v1/chat/conversations/${encodeURIComponent(conversationId)}/regenerate`, {
    method: 'POST',
    signal,
  });
}

async function* openStream(
  path: string,
  init: { method: string; body?: string; signal?: AbortSignal },
): AsyncGenerator<ChatStreamEvent, void> {
  const correlationId = newCorrelationId();

  let response: Response;
  try {
    response = await fetch(`${env.VITE_API_BASE_URL}${path}`, {
      method: init.method,
      headers: {
        Accept: 'text/event-stream',
        ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        [CORRELATION_ID_HEADER]: correlationId,
      },
      body: init.body,
      signal: init.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      // The user cancelled before the response arrived. Not a failure.
      return;
    }
    throw new ApiError({
      message: 'Could not reach the platform API. Check your connection and try again.',
      category: 'network',
      status: 0,
      correlationId,
    });
  }

  if (!response.ok) {
    // The backend validates before opening the stream, so a bad request is a
    // real status code and can be surfaced as one.
    throw await toApiError(response, correlationId);
  }

  if (!response.body) {
    throw new ApiError({
      message: 'The server returned no response body.',
      category: 'unexpected',
      status: response.status,
      correlationId,
    });
  }

  for await (const frame of parseSseFrames(response.body, init.signal)) {
    const parsed = chatStreamEventSchema.safeParse(JSON.parse(frame.data) as unknown);
    if (!parsed.success) {
      throw new ApiError({
        message: 'The server sent an event in an unexpected format.',
        category: 'unexpected',
        status: response.status,
        correlationId,
      });
    }
    yield parsed.data;
  }
}
