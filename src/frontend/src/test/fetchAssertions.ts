/**
 * Helpers for asserting on stubbed `fetch` calls.
 *
 * `fetch` accepts `string | URL | Request` for its target and a `BodyInit` for
 * its body, so `String(call[0])` is unsound — it stringifies a `Request` to
 * `[object Object]` and an assertion against it would pass or fail for the
 * wrong reason. These narrow properly instead.
 */

/** Return the URL a stubbed `fetch` call targeted. */
export function requestUrl(call: readonly [RequestInfo | URL, RequestInit?] | undefined): string {
  const target = call?.[0];

  if (typeof target === 'string') {
    return target;
  }
  if (target instanceof URL) {
    return target.href;
  }
  return target?.url ?? '';
}

/** Return the parsed JSON body of a stubbed `fetch` call. */
export function requestBody(call: readonly [RequestInfo | URL, RequestInit?] | undefined): unknown {
  const body = call?.[1]?.body;
  return typeof body === 'string' ? JSON.parse(body) : undefined;
}

/** Return the HTTP method of a stubbed `fetch` call. */
export function requestMethod(
  call: readonly [RequestInfo | URL, RequestInit?] | undefined,
): string | undefined {
  return call?.[1]?.method;
}
