/**
 * Spend broken down by model, provider and agent.
 *
 * The summary answers "how much"; this answers "because of what", which is the
 * question that leads to a decision. A total nobody can attribute is a total
 * nobody can act on.
 *
 * Rows arrive already ordered most expensive first, and that ordering is stable
 * between refreshes — a table that reshuffles looks broken even when its numbers
 * are right. This component does not re-sort them.
 *
 * A bar shows each row's share of the total. It is deliberately a proportion of
 * *cost*, not of calls: a model called twice as often but priced ten times
 * lower is not the one to look at first.
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatCost, formatTokens, useCostSummary } from '@/features/cost-analytics/useCostSummary';
import type { CostBreakdown } from '@/api/types';

/** Grouping shown, in the order an operator usually reasons about them. */
const GROUPINGS = [
  { key: 'by_model', label: 'By model' },
  { key: 'by_provider', label: 'By provider' },
  { key: 'by_agent', label: 'By agent' },
] as const;

function share(row: CostBreakdown, total: number): number {
  if (total <= 0) {
    // Everything free, or nothing recorded. A full bar on every row would imply
    // a meaningful split where there is none.
    return 0;
  }
  return Math.min(100, (Number(row.usage.estimated_cost) / total) * 100);
}

function BreakdownRow({
  row,
  total,
  currency,
}: {
  row: CostBreakdown;
  total: number;
  currency: string;
}) {
  const percentage = share(row, total);

  return (
    <li className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate font-mono text-sm" title={row.key}>
          {row.key}
        </span>
        <span className="shrink-0 text-sm tabular-nums">
          {formatCost(row.usage.estimated_cost, currency)}
        </span>
      </div>

      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        // Presentational: the numbers either side are the accessible content,
        // and a screen reader announcing a bar width adds nothing.
        aria-hidden="true"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${percentage}%` }} />
      </div>

      <p className="text-xs text-muted-foreground">
        {formatTokens(row.usage.invocations)} call
        {row.usage.invocations === 1 ? '' : 's'} ·{' '}
        {formatTokens(row.usage.prompt_tokens + row.usage.completion_tokens)} tokens
        {row.usage.failures > 0 ? ` · ${formatTokens(row.usage.failures)} failed` : ''}
      </p>
    </li>
  );
}

export function CostBreakdownCard() {
  const { data, isPending, isError } = useCostSummary();

  // The summary card already reports the error with its correlation id.
  // Repeating it here would make one backend failure look like two.
  if (isPending || isError) {
    return null;
  }

  const total = Number(data.summary.overall.estimated_cost);
  const populated = GROUPINGS.filter(({ key }) => data.summary[key].length > 0);

  if (populated.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>What it is being spent on</CardTitle>
        <CardDescription>
          Ordered by cost. Bars show each entry&rsquo;s share of the total, not its share of calls.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {populated.map(({ key, label }) => (
          <section key={key} className="flex flex-col gap-3">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {label}
            </h3>
            <ul className="flex flex-col gap-3">
              {data.summary[key].map((row) => (
                <BreakdownRow
                  key={row.key}
                  row={row}
                  total={total}
                  currency={data.summary.currency}
                />
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}
