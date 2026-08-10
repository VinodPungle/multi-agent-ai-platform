/**
 * Data hook for the cost analytics feature.
 *
 * Separated from presentation for the same reason as the platform status hook:
 * the caching policy lives in one place and the components stay pure.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiError } from '@/api/client';
import { fetchCostSummary, platformQueryKeys } from '@/api/platform';
import type { CostSummaryResponse } from '@/api/types';

/**
 * How often the totals are re-fetched while the tab is visible.
 *
 * Slower than the health poll. Spend changes only when someone sends a message,
 * and a figure that ticks every few seconds invites people to watch it rather
 * than read it. Thirty seconds is frequent enough to see the effect of a
 * conversation without turning a cost panel into a stock ticker.
 */
const COST_REFRESH_INTERVAL_MS = 30_000;

/** Live cost and usage totals for the replica that answers the request. */
export function useCostSummary(): UseQueryResult<CostSummaryResponse, ApiError> {
  return useQuery({
    queryKey: platformQueryKeys.costs(),
    queryFn: ({ signal }) => fetchCostSummary({ signal }),
    refetchInterval: COST_REFRESH_INTERVAL_MS,
    // Zero, like health: a cached total is misleading the moment a request has
    // been sent, and this panel exists to reflect what just happened.
    staleTime: 0,
  });
}

/**
 * Format an estimated cost for display.
 *
 * The value arrives as a string because the backend sums money as `Decimal`;
 * it is parsed here **only** to choose a number of decimal places, and the
 * result is never fed back into arithmetic.
 *
 * Four decimal places below one unit of currency, two above it. A handful of chat turns
 * costs fractions of a cent, and rounding those to `$0.00` — or `$0.03` when
 * the figure is `0.0342` — throws away the only digits that carry information
 * at the scale this panel usually shows. Above a pound the extra places are
 * noise.
 *
 * The currency comes from the backend rather than being assumed. Rates are
 * configured in whatever the subscription bills in — an INR figure rendered
 * with a dollar sign understates the bill by an order of magnitude, which is
 * exactly the kind of wrong that gets believed.
 */
export function formatCost(value: string, currency = 'USD'): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    // The backend sent something unexpected. Showing it verbatim is more useful
    // than showing `NaN`, and more honest than showing zero.
    return value;
  }
  // `Intl` knows the right symbol, placement and grouping for each currency —
  // ₹1,23,456.78 groups differently from $123,456.78, and hand-formatting gets
  // that wrong for exactly the audience most likely to notice.
  const digits = amount !== 0 && amount < 1 ? 4 : 2;
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(amount);
  } catch {
    // An unrecognised code. Showing the amount beside the raw code beats
    // throwing inside a render.
    return `${amount.toFixed(digits)} ${currency}`;
  }
}

/** Format a token count with thousands separators. */
export function formatTokens(value: number): string {
  return value.toLocaleString();
}

/** Format a duration in milliseconds, in whichever unit reads better. */
export function formatLatency(milliseconds: number): string {
  if (milliseconds === 0) {
    return '—';
  }
  return milliseconds >= 1000
    ? `${(milliseconds / 1000).toFixed(2)} s`
    : `${Math.round(milliseconds)} ms`;
}
