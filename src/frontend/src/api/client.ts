/**
 * The centralised API client.
 *
 * The handbook forbids calling `fetch()` directly around the application. Every
 * backend call goes through here, which is what makes correlation, timeouts,
 * error normalisation and (later) authentication and streaming a single
 * implementation rather than a convention that erodes.
 *
 * Responsibilities, per the handbook's "API Layer":
 * authentication (future), error handling, retries (delegated to TanStack
 * Query), request ids, streaming (Milestone 02) and timeouts.
 */

import { z } from 'zod';

import { env } from '@/config/env';
import { errorResponseSchema, type ErrorCategory } from '@/api/types';

/** Header the backend reads to continue an existing trace. */
export const CORRELATION_ID_HEADER = 'X-Correlation-ID';

/** Header the backend echoes for a single request. */
export const REQUEST_ID_HEADER = 'X-Request-ID';

/** Default per-request budget. A hung request must not hang the UI forever. */
const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * A normalised API failure.
 *
 * Carries the correlation id so a user-facing error message can quote the exact
 * identifier an operator needs to find the matching server-side trace.
 */
export class ApiError extends Error {
  readonly category: ErrorCategory;
  readonly status: number;
  readonly correlationId: string | null;
  readonly fields: readonly { location: string; message: string }[];

  constructor(params: {
    message: string;
    category: ErrorCategory;
    status: number;
    correlationId: string | null;
    fields?: readonly { location: string; message: string }[];
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.category = params.category;
    this.status = params.status;
    this.correlationId = params.correlationId;
    this.fields = params.fields ?? [];
  }

  /**
   * Whether retrying could plausibly succeed.
   *
   * Mirrors the backend's `RetryPolicy`: transport and upstream failures are
   * transient; validation and policy failures are deterministic and retrying
   * them only delays the error the user needs to see.
   */
  get isRetryable(): boolean {
    return (
      this.category === 'network' || this.category === 'provider' || this.category === 'timeout'
    );
  }
}

export interface RequestOptions {
  /** HTTP method. Defaults to `GET`. */
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** JSON-serialisable request body. */
  body?: unknown;
  /** Overrides {@link DEFAULT_TIMEOUT_MS}. */
  timeoutMs?: number;
  /** Caller-controlled cancellation, combined with the timeout signal. */
  signal?: AbortSignal;
  /** Continues an existing trace. Generated when omitted. */
  correlationId?: string;
}

/**
 * Generate a correlation id for an outbound request.
 *
 * `crypto.randomUUID` is unavailable on insecure origins, which includes some
 * LAN development setups, so a non-cryptographic fallback is used there. The id
 * only needs to be unique, never unguessable.
 */
function newCorrelationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

async function toApiError(response: Response, correlationId: string): Promise<ApiError> {
  const headerCorrelationId = response.headers.get(CORRELATION_ID_HEADER) ?? correlationId;

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    // A non-JSON error body means the failure happened before our handlers ran
    // — a proxy, a gateway, or a crashed worker.
    return new ApiError({
      message: `The server returned an unreadable response (HTTP ${response.status}).`,
      category: response.status >= 500 ? 'unexpected' : 'validation',
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

/**
 * Perform a request and validate the response against `schema`.
 *
 * @param path   Path relative to the API base URL, beginning with `/`.
 * @param schema Zod schema the response body must satisfy.
 * @param options Request options.
 * @throws {ApiError} on any transport, HTTP or validation failure.
 */
export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestOptions = {},
): Promise<T> {
  const correlationId = options.correlationId ?? newCorrelationId();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  const timeoutController = new AbortController();
  const timeoutHandle = setTimeout(() => {
    timeoutController.abort();
  }, timeoutMs);

  // Either the caller cancelling or the timeout firing aborts the request.
  const signals = [timeoutController.signal];
  if (options.signal) {
    signals.push(options.signal);
  }

  try {
    const response = await fetch(`${env.VITE_API_BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers: {
        Accept: 'application/json',
        ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        [CORRELATION_ID_HEADER]: correlationId,
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: AbortSignal.any(signals),
    });

    if (!response.ok) {
      throw await toApiError(response, correlationId);
    }

    const payload: unknown = await response.json();
    const parsed = schema.safeParse(payload);

    if (!parsed.success) {
      // A shape mismatch is a contract break. Failing here localises it to the
      // boundary rather than letting `undefined` surface inside a component.
      throw new ApiError({
        message: 'The server response did not match the expected format.',
        category: 'unexpected',
        status: response.status,
        correlationId: response.headers.get(CORRELATION_ID_HEADER) ?? correlationId,
      });
    }

    return parsed.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === 'AbortError') {
      // Distinguishing our timeout from the caller's cancellation matters: one
      // is a failure worth reporting, the other is expected navigation.
      const causedByTimeout = timeoutController.signal.aborted;
      throw new ApiError({
        message: causedByTimeout
          ? `The request took longer than ${Math.round(timeoutMs / 1000)} seconds and was cancelled.`
          : 'The request was cancelled.',
        category: causedByTimeout ? 'timeout' : 'network',
        status: 0,
        correlationId,
      });
    }

    // `fetch` rejects only on transport failure: offline, DNS, TLS, CORS.
    throw new ApiError({
      message: 'Could not reach the platform API. Check your connection and try again.',
      category: 'network',
      status: 0,
      correlationId,
    });
  } finally {
    clearTimeout(timeoutHandle);
  }
}
