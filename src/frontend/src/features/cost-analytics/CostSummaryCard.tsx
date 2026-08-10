/**
 * Headline spend and usage.
 *
 * The four numbers an operator checks first: what it has cost, how many turns
 * produced that, how many failed, and how slow they were.
 *
 * The scope line is rendered, not tucked into a tooltip. Totals are counted in
 * one process and reset on restart; a reader who takes them for the platform's
 * whole spend would be badly wrong, and the cheapest way to prevent that is to
 * say so on the card.
 */

import { ApiError } from '@/api/client';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  formatCost,
  formatLatency,
  formatTokens,
  useCostSummary,
} from '@/features/cost-analytics/useCostSummary';
import type { UsageTotals } from '@/api/types';

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-2xl font-semibold tabular-nums tracking-tight">{value}</dd>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Metrics({ totals }: { totals: UsageTotals }) {
  const tokens = totals.prompt_tokens + totals.completion_tokens;

  return (
    <dl className="grid grid-cols-2 gap-5 sm:grid-cols-4">
      <Metric
        label="Estimated cost"
        value={formatCost(totals.estimated_cost)}
        hint="From configured prices"
      />
      <Metric
        label="Model calls"
        value={formatTokens(totals.invocations)}
        hint={
          // Failures are shown as a count beside the total rather than as a
          // rate: a percentage hides whether it is two failures or two thousand.
          totals.failures > 0 ? `${formatTokens(totals.failures)} failed` : 'None failed'
        }
      />
      <Metric
        label="Tokens"
        value={formatTokens(tokens)}
        hint={`${formatTokens(totals.prompt_tokens)} in / ${formatTokens(totals.completion_tokens)} out`}
      />
      <Metric
        label="Mean latency"
        value={formatLatency(totals.average_latency_ms)}
        hint="A mean, not a percentile"
      />
    </dl>
  );
}

function ErrorState({ error }: { error: ApiError }) {
  return (
    <div role="alert" className="flex flex-col gap-2">
      <Badge variant="danger">Unavailable</Badge>
      <p className="text-sm text-muted-foreground">{error.message}</p>
      {error.correlationId ? (
        <p className="text-xs text-muted-foreground">
          Correlation ID: <code className="font-mono">{error.correlationId}</code>
        </p>
      ) : null}
    </div>
  );
}

export function CostSummaryCard() {
  const { data, error, isPending, isError } = useCostSummary();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Spend</CardTitle>
        <CardDescription>
          Token usage and estimated cost for every model call this replica has served.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isPending ? (
          <p className="text-sm text-muted-foreground" aria-live="polite">
            Loading…
          </p>
        ) : isError ? (
          <ErrorState error={error} />
        ) : data.summary.overall.invocations === 0 ? (
          // An empty state that says what to do, rather than four zeros that
          // look like a broken panel.
          <p className="text-sm text-muted-foreground">
            Nothing recorded yet. Send a message in Chat and the totals appear here.
          </p>
        ) : (
          <Metrics totals={data.summary.overall} />
        )}

        {!isPending && !isError ? (
          <p className="border-t border-border pt-3 text-xs text-muted-foreground">{data.scope}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
