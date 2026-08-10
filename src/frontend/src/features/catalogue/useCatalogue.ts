/**
 * Data hooks for the discovery pages.
 *
 * All three are cached indefinitely. Registries are written once at startup and
 * read thereafter, so a deployment's agents, tools and models cannot change
 * while the page is open — polling them would spend requests to re-learn a
 * constant.
 *
 * That is also the honest signal: if this page looks stale, the platform was
 * restarted, and a reload is the correct way to see the change.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiError } from '@/api/client';
import { fetchAgents, fetchModels, fetchTools, platformQueryKeys } from '@/api/platform';
import type { AgentSummary, ModelSummary, ToolSummary } from '@/api/types';

export function useAgents(): UseQueryResult<AgentSummary[], ApiError> {
  return useQuery({
    queryKey: platformQueryKeys.agents(),
    queryFn: ({ signal }) => fetchAgents({ signal }),
    staleTime: Infinity,
  });
}

export function useTools(): UseQueryResult<ToolSummary[], ApiError> {
  return useQuery({
    queryKey: platformQueryKeys.tools(),
    queryFn: ({ signal }) => fetchTools({ signal }),
    staleTime: Infinity,
  });
}

export function useModels(): UseQueryResult<ModelSummary[], ApiError> {
  return useQuery({
    queryKey: platformQueryKeys.models(),
    queryFn: ({ signal }) => fetchModels({ signal }),
    staleTime: Infinity,
  });
}

/**
 * Format a published price per million tokens.
 *
 * Zero is rendered as "not priced" rather than "$0.00". A model with no
 * configured price genuinely costs something; the platform simply has not been
 * told what, and showing free would make every cost figure derived from it
 * quietly wrong.
 */
export function formatPrice(value: string | number): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return String(value);
  }
  if (amount === 0) {
    return 'Not priced';
  }
  return `$${amount.toFixed(2)}/M`;
}

/** Format a token count compactly — context windows run to seven digits. */
export function formatTokenLimit(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`;
  }
  if (value >= 1_000) {
    return `${Math.round(value / 1_000)}K`;
  }
  return String(value);
}
