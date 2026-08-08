/**
 * Platform endpoints.
 *
 * One module per backend feature area. Components never construct paths; they
 * call these functions, so a route change is a one-line edit here.
 */

import { request, type RequestOptions } from '@/api/client';
import {
  healthResponseSchema,
  platformInfoSchema,
  type HealthResponse,
  type PlatformInfo,
} from '@/api/types';

/** Query keys for TanStack Query, kept beside the calls they identify. */
export const platformQueryKeys = {
  all: ['platform'] as const,
  health: () => [...platformQueryKeys.all, 'health'] as const,
  info: () => [...platformQueryKeys.all, 'info'] as const,
};

/**
 * Fetch the detailed platform health report.
 *
 * Served from the application root, not the versioned API: probes are
 * infrastructure and must not move when the API is versioned.
 */
export function fetchHealth(options?: RequestOptions): Promise<HealthResponse> {
  return request('/health', healthResponseSchema, options);
}

/** Fetch platform identity and effective feature flags. */
export function fetchPlatformInfo(options?: RequestOptions): Promise<PlatformInfo> {
  return request('/api/v1/info', platformInfoSchema, options);
}
