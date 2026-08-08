/**
 * Platform endpoints.
 *
 * One module per backend feature area. Components never construct paths; they
 * call these functions, so a route change is a one-line edit here.
 */

import { request, type RequestOptions } from '@/api/client';
import { conversationSchema, type Conversation } from '@/api/chat';
import {
  healthResponseSchema,
  platformInfoSchema,
  type HealthResponse,
  type PlatformInfo,
} from '@/api/types';
import { z } from 'zod';

/** Query keys for TanStack Query, kept beside the calls they identify. */
export const platformQueryKeys = {
  all: ['platform'] as const,
  health: () => [...platformQueryKeys.all, 'health'] as const,
  info: () => [...platformQueryKeys.all, 'info'] as const,
};

export const chatQueryKeys = {
  all: ['chat'] as const,
  conversation: (id: string) => [...chatQueryKeys.all, 'conversation', id] as const,
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

/**
 * Fetch a conversation's stored messages.
 *
 * An unknown conversation returns an empty list rather than a 404, so restoring
 * a view that was never written to is not an error path.
 */
export function fetchConversation(
  conversationId: string,
  options?: RequestOptions,
): Promise<Conversation> {
  return request(
    `/api/v1/chat/conversations/${encodeURIComponent(conversationId)}`,
    conversationSchema,
    options,
  );
}

/** Forget a conversation. Succeeds whether or not it existed. */
export function clearConversation(
  conversationId: string,
  options?: RequestOptions,
): Promise<unknown> {
  // 204 No Content: there is no body to validate, so the schema accepts
  // anything rather than pretending to check a payload that cannot exist.
  return request(`/api/v1/chat/conversations/${encodeURIComponent(conversationId)}`, z.unknown(), {
    ...options,
    method: 'DELETE',
  });
}
