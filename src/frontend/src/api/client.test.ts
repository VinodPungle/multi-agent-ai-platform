/**
 * API client behaviour.
 *
 * The client is the single boundary between the application and the backend, so
 * its failure handling is worth pinning precisely: every branch here decides
 * what a user sees when something goes wrong.
 */

import { describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { ApiError, CORRELATION_ID_HEADER, request } from '@/api/client';
import { jsonResponse } from '@/test/utils';

const testSchema = z.object({ value: z.string() });

function stubFetch(response: Response | Promise<Response> | Error) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
    if (response instanceof Error) {
      return Promise.reject(response);
    }
    return Promise.resolve(response);
  });
}

describe('request', () => {
  it('returns the parsed body on success', async () => {
    stubFetch(jsonResponse({ value: 'ok' }));

    await expect(request('/test', testSchema)).resolves.toEqual({ value: 'ok' });
  });

  it('prefixes the configured API base URL', async () => {
    const fetchSpy = stubFetch(jsonResponse({ value: 'ok' }));

    await request('/test', testSchema);

    expect(fetchSpy.mock.calls[0]![0]).toBe('http://api.test/test');
  });

  it('sends a correlation id so the trace can be joined server-side', async () => {
    const fetchSpy = stubFetch(jsonResponse({ value: 'ok' }));

    await request('/test', testSchema);

    const init = fetchSpy.mock.calls[0]![1]!;
    const headers = init.headers as Record<string, string>;
    expect(headers[CORRELATION_ID_HEADER]).toBeTruthy();
  });

  it('honours a caller-supplied correlation id', async () => {
    const fetchSpy = stubFetch(jsonResponse({ value: 'ok' }));

    await request('/test', testSchema, { correlationId: 'existing-trace' });

    const init = fetchSpy.mock.calls[0]![1]!;
    const headers = init.headers as Record<string, string>;
    expect(headers[CORRELATION_ID_HEADER]).toBe('existing-trace');
  });

  it('serialises a request body and sets the content type', async () => {
    const fetchSpy = stubFetch(jsonResponse({ value: 'ok' }));

    await request('/test', testSchema, { method: 'POST', body: { name: 'agent' } });

    const init = fetchSpy.mock.calls[0]![1]!;
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"name":"agent"}');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('omits the content type when there is no body', async () => {
    const fetchSpy = stubFetch(jsonResponse({ value: 'ok' }));

    await request('/test', testSchema);

    const init = fetchSpy.mock.calls[0]![1]!;
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });
});

describe('error handling', () => {
  it('translates the platform error envelope', async () => {
    stubFetch(
      jsonResponse(
        {
          error: {
            category: 'not_found',
            message: "Agent 'unknown' is not registered",
            correlation_id: 'corr-123',
            fields: [],
          },
        },
        { status: 404 },
      ),
    );

    const error = await request('/test', testSchema).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Agent 'unknown' is not registered");
    expect((error as ApiError).category).toBe('not_found');
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).correlationId).toBe('corr-123');
  });

  it('surfaces field-level validation detail', async () => {
    stubFetch(
      jsonResponse(
        {
          error: {
            category: 'validation',
            message: 'Request validation failed',
            correlation_id: 'corr-456',
            fields: [{ location: 'body.temperature', message: 'less than or equal to 2' }],
          },
        },
        { status: 422 },
      ),
    );

    const error = (await request('/test', testSchema).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error.fields).toHaveLength(1);
    expect(error.fields[0]!.location).toBe('body.temperature');
  });

  it('handles an error body that is not JSON', async () => {
    // A gateway or crashed worker replies before our handlers ever run.
    stubFetch(new Response('<html>502 Bad Gateway</html>', { status: 502 }));

    const error = (await request('/test', testSchema).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.message).toContain('unreadable');
  });

  it('falls back to the header correlation id when the body omits it', async () => {
    stubFetch(
      new Response('not json', {
        status: 500,
        headers: { [CORRELATION_ID_HEADER]: 'corr-from-header' },
      }),
    );

    const error = (await request('/test', testSchema).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error.correlationId).toBe('corr-from-header');
  });

  it('reports a transport failure as a network error', async () => {
    stubFetch(new TypeError('Failed to fetch'));

    const error = (await request('/test', testSchema).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error.category).toBe('network');
    expect(error.status).toBe(0);
    expect(error.message).toContain('Could not reach');
  });

  it('rejects a response whose shape does not match the contract', async () => {
    // Failing at the boundary localises a contract break, instead of letting
    // `undefined` surface deep inside a component.
    stubFetch(jsonResponse({ unexpected: 'shape' }));

    const error = (await request('/test', testSchema).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error.category).toBe('unexpected');
    expect(error.message).toContain('did not match');
  });

  it('times out a request that never resolves', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        }),
    );

    const error = (await request('/test', testSchema, { timeoutMs: 10 }).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error.category).toBe('timeout');
    expect(error.message).toContain('cancelled');
  });

  it('distinguishes caller cancellation from a timeout', async () => {
    const controller = new AbortController();

    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        }),
    );

    const pending = request('/test', testSchema, { signal: controller.signal, timeoutMs: 60_000 });
    controller.abort();

    const error = (await pending.catch((caught: unknown) => caught)) as ApiError;

    expect(error.category).toBe('network');
    expect(error.message).toBe('The request was cancelled.');
  });
});

describe('ApiError.isRetryable', () => {
  it.each(['network', 'provider', 'timeout'] as const)('treats %s as retryable', (category) => {
    const error = new ApiError({ message: 'x', category, status: 502, correlationId: null });

    expect(error.isRetryable).toBe(true);
  });

  it.each(['validation', 'not_found', 'policy_violation', 'configuration'] as const)(
    'treats %s as non-retryable',
    (category) => {
      // Retrying a deterministic failure only delays the error the user needs.
      const error = new ApiError({ message: 'x', category, status: 422, correlationId: null });

      expect(error.isRetryable).toBe(false);
    },
  );
});
