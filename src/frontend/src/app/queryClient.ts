/**
 * TanStack Query configuration.
 *
 * Kept out of `providers.tsx` so that module exports only components — a file
 * mixing components with other exports breaks Fast Refresh, which silently
 * degrades the development loop.
 */

import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/api/client';

/** Attempts after the first, for failures worth retrying. */
const MAX_RETRIES = 2;

/** Ceiling on a single backoff delay. */
const MAX_RETRY_DELAY_MS = 10_000;

/** How long fetched data is considered fresh by default. */
const DEFAULT_STALE_TIME_MS = 30_000;

/**
 * Build a query client with the platform's caching and retry policy.
 *
 * A factory rather than a module-level singleton: a shared client would leak
 * cached data between tests and between server-rendered requests.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Retry decisions mirror the backend's `RetryPolicy`: a validation or
        // not-found failure is deterministic, so retrying only delays the error
        // the user needs to see.
        retry: (failureCount, error) => {
          if (error instanceof ApiError) {
            return error.isRetryable && failureCount < MAX_RETRIES;
          }
          return failureCount < MAX_RETRIES;
        },
        retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, MAX_RETRY_DELAY_MS),
        // Refetching on every window focus is surprising and, once model calls
        // cost money, expensive. Data that must stay live opts in per query.
        refetchOnWindowFocus: false,
        staleTime: DEFAULT_STALE_TIME_MS,
      },
    },
  });
}
