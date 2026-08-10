/**
 * The cost dashboard.
 *
 * Two things are worth testing beyond "it renders a number":
 *
 * - **The scope line is always shown.** Totals are per-replica and reset on
 *   restart. A reader who takes them for the platform's whole spend is badly
 *   wrong, and the card is the only place that says otherwise.
 * - **Sub-cent costs are not rounded to zero.** A handful of chat turns costs
 *   fractions of a cent, and `$0.00` makes a working panel look broken exactly
 *   when someone is checking whether it works.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { CostBreakdownCard } from '@/features/cost-analytics/CostBreakdownCard';
import { CostSummaryCard } from '@/features/cost-analytics/CostSummaryCard';
import { formatCost, formatLatency } from '@/features/cost-analytics/useCostSummary';
import { jsonResponse, renderWithProviders } from '@/test/utils';

/** Stub the analytics endpoint, whatever form `fetch` was called with. */
function stubCosts(payload: unknown): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(jsonResponse(payload)));
}

afterEach(() => {
  vi.restoreAllMocks();
});

const EMPTY = {
  summary: {
    currency: 'USD',
    overall: {
      invocations: 0,
      failures: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      estimated_cost: '0',
      average_latency_ms: 0,
    },
    by_model: [],
    by_provider: [],
    by_agent: [],
  },
  scope: 'This process since startup. Totals reset on restart.',
};

const POPULATED = {
  summary: {
    currency: 'USD',
    overall: {
      invocations: 12,
      failures: 2,
      prompt_tokens: 8_400,
      completion_tokens: 2_100,
      estimated_cost: '0.0342',
      average_latency_ms: 1840,
    },
    by_model: [
      {
        key: 'fw-kimi-k3',
        usage: {
          invocations: 9,
          failures: 2,
          prompt_tokens: 7_000,
          completion_tokens: 1_800,
          estimated_cost: '0.0300',
          average_latency_ms: 2100,
        },
      },
      {
        key: 'mock-echo',
        usage: {
          invocations: 3,
          failures: 0,
          prompt_tokens: 1_400,
          completion_tokens: 300,
          estimated_cost: '0.0042',
          average_latency_ms: 40,
        },
      },
    ],
    by_provider: [
      {
        key: 'azure-foundry',
        usage: {
          invocations: 9,
          failures: 2,
          prompt_tokens: 7_000,
          completion_tokens: 1_800,
          estimated_cost: '0.0300',
          average_latency_ms: 2100,
        },
      },
    ],
    by_agent: [],
  },
  scope: 'This process since startup. Totals reset on restart.',
};

describe('formatCost', () => {
  it('renders the currency the backend reported, not an assumed dollar', () => {
    // An INR figure shown with a dollar sign understates the bill by an order
    // of magnitude — and looks entirely plausible while doing it.
    expect(formatCost('420.86', 'INR')).toContain('420.86');
    expect(formatCost('420.86', 'INR')).not.toContain('$');
  });

  it('renders an unrecognised but well-formed code beside the amount', () => {
    // Intl accepts any three-letter code and uses it in place of a symbol,
    // rather than throwing. Verified, not assumed.
    expect(formatCost('12.5', 'ZZZ')).toContain('12.50');
  });

  it('falls back rather than throwing inside a render on a malformed code', () => {
    // Intl throws RangeError for anything that is not three letters — a render
    // is the worst place to discover that.
    expect(formatCost('12.5', 'US')).toBe('12.50 US');
  });

  it('shows sub-cent amounts to four places rather than rounding to zero', () => {
    expect(formatCost('0.0042')).toBe('$0.0042');
  });

  it('shows amounts under one unit of currency to four places', () => {
    // `$0.03` for `0.0342` throws away the digits that carry information at
    // the scale this panel usually shows.
    expect(formatCost('0.0342')).toBe('$0.0342');
  });

  it('shows larger amounts to two places, where the extra digits are noise', () => {
    expect(formatCost('12.5')).toBe('$12.50');
  });

  it('shows zero explicitly rather than as an empty value', () => {
    expect(formatCost('0')).toBe('$0.00');
  });

  it('shows an unparseable value verbatim rather than NaN', () => {
    // More useful than "NaN" and more honest than "$0.00".
    expect(formatCost('not-a-number')).toBe('not-a-number');
  });
});

describe('formatLatency', () => {
  it('switches to seconds once milliseconds stop being readable', () => {
    expect(formatLatency(1840)).toBe('1.84 s');
    expect(formatLatency(240)).toBe('240 ms');
  });

  it('shows nothing measured as a dash', () => {
    expect(formatLatency(0)).toBe('—');
  });
});

describe('CostSummaryCard', () => {
  it('tells the user how to populate it when nothing has been recorded', async () => {
    stubCosts(EMPTY);
    renderWithProviders(<CostSummaryCard />);

    expect(await screen.findByText(/Send a message in Chat/i)).toBeInTheDocument();
  });

  it('always states what the numbers cover', async () => {
    stubCosts(EMPTY);
    renderWithProviders(<CostSummaryCard />);

    expect(await screen.findByText(/Totals reset on restart/i)).toBeInTheDocument();
  });

  it('shows the headline cost', async () => {
    stubCosts(POPULATED);
    renderWithProviders(<CostSummaryCard />);

    expect(await screen.findByText('$0.0342')).toBeInTheDocument();
  });

  it('reports failures as a count beside the total', async () => {
    stubCosts(POPULATED);
    renderWithProviders(<CostSummaryCard />);

    expect(await screen.findByText('12')).toBeInTheDocument();
    expect(await screen.findByText(/2 failed/)).toBeInTheDocument();
  });
});

describe('CostBreakdownCard', () => {
  it('attributes spend to each model', async () => {
    stubCosts(POPULATED);
    renderWithProviders(<CostBreakdownCard />);

    expect(await screen.findByText('fw-kimi-k3')).toBeInTheDocument();
    expect(await screen.findByText('mock-echo')).toBeInTheDocument();
  });

  it('omits a grouping the backend has nothing for', async () => {
    stubCosts(POPULATED);
    renderWithProviders(<CostBreakdownCard />);

    // `by_agent` is empty in this fixture: an empty heading would be furniture
    // implying data that does not exist.
    await screen.findByText('By model');
    expect(screen.queryByText('By agent')).not.toBeInTheDocument();
  });

  it('renders nothing at all when no spend has been recorded', async () => {
    stubCosts(EMPTY);
    const { container } = renderWithProviders(<CostBreakdownCard />);

    // The summary card already covers the empty case; a second empty panel
    // beside it would be noise.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.textContent).toBe('');
  });
});
