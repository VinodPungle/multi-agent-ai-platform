/**
 * Data hooks for the platform status feature.
 *
 * Data fetching is separated from presentation (handbook, "Component Design"),
 * so the status components stay pure and testable and the caching policy lives
 * in one place.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiError } from '@/api/client';
import { fetchHealth, fetchPlatformInfo, platformQueryKeys } from '@/api/platform';
import type { HealthResponse, PlatformInfo } from '@/api/types';

/** How often health is re-checked while the tab is visible. */
const HEALTH_REFRESH_INTERVAL_MS = 15_000;

/**
 * Live platform health.
 *
 * Polled rather than fetched once: health is the one thing on this screen that
 * changes without the user doing anything. `staleTime` is zero for the same
 * reason — a cached "healthy" is worthless if the platform has since degraded.
 */
export function usePlatformHealth(): UseQueryResult<HealthResponse, ApiError> {
  return useQuery({
    queryKey: platformQueryKeys.health(),
    queryFn: ({ signal }) => fetchHealth({ signal }),
    refetchInterval: HEALTH_REFRESH_INTERVAL_MS,
    staleTime: 0,
  });
}

/**
 * Platform identity and feature flags.
 *
 * Effectively static for the lifetime of a deployment, so it is cached
 * indefinitely rather than re-fetched on every mount.
 */
export function usePlatformInfo(): UseQueryResult<PlatformInfo, ApiError> {
  return useQuery({
    queryKey: platformQueryKeys.info(),
    queryFn: ({ signal }) => fetchPlatformInfo({ signal }),
    staleTime: Infinity,
  });
}
