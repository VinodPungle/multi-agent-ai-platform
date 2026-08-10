/**
 * Model evaluation metrics.
 *
 * Built from the same evaluation records that feed cost analytics, presented by
 * the question they answer here: *how is each model behaving?* rather than
 * *what is it costing?*
 *
 * What this deliberately does not claim
 *   There is no quality score. The platform measures latency, failures and
 *   token consumption because those are facts it observes; whether an answer
 *   was any *good* needs a judge and a labelled set, and neither exists.
 *   Inventing a score from cost or speed would be worse than showing none,
 *   because a number on a dashboard gets believed.
 *
 *   `CLAUDE.md` calls this out as "Future Quality Score", and it stays future.
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
import type { CostBreakdown } from '@/api/types';

function ErrorState({ error }: { error: ApiError }) {
  return (
    <div role="alert" className="flex flex-col gap-2">
      <Badge variant="danger">Unavailable</Badge>
      <p className="text-sm text-muted-foreground">{error.message}</p>
    </div>
  );
}

/** Tokens generated per call — a rough measure of how much a model says. */
function verbosity(row: CostBreakdown): string {
  if (row.usage.invocations === 0) {
    return '—';
  }
  return formatTokens(Math.round(row.usage.completion_tokens / row.usage.invocations));
}

function failureRate(row: CostBreakdown): { label: string; failing: boolean } {
  if (row.usage.invocations === 0) {
    return { label: '—', failing: false };
  }
  const percentage = (row.usage.failures / row.usage.invocations) * 100;
  return {
    label: `${percentage.toFixed(percentage % 1 === 0 ? 0 : 1)}%`,
    failing: row.usage.failures > 0,
  };
}

function ModelRow({ row }: { row: CostBreakdown }) {
  const failures = failureRate(row);

  return (
    <tr className="border-t border-border">
      <td className="py-3 pr-4 font-mono text-sm">{row.key}</td>
      <td className="py-3 pr-4 text-right text-sm tabular-nums">
        {formatTokens(row.usage.invocations)}
      </td>
      <td className="py-3 pr-4 text-right text-sm tabular-nums">
        {failures.failing ? <span className="text-danger">{failures.label}</span> : failures.label}
      </td>
      <td className="py-3 pr-4 text-right text-sm tabular-nums">
        {formatLatency(row.usage.average_latency_ms)}
      </td>
      <td className="py-3 pr-4 text-right text-sm tabular-nums">{verbosity(row)}</td>
      <td className="py-3 text-right text-sm tabular-nums">
        {formatCost(row.usage.estimated_cost)}
      </td>
    </tr>
  );
}

export function EvaluationsPage() {
  const { data, error, isPending, isError } = useCostSummary();

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Evaluations</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          How each model is behaving, from the evaluation record the runtime writes for every call —
          including the ones that failed, which consumed tokens too.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>By model</CardTitle>
          <CardDescription>
            Measured, not judged. There is no quality score here: whether an answer was good needs a
            judge and a labelled set, and inventing a number from speed or cost would only get
            believed.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isPending ? (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              Loading…
            </p>
          ) : isError ? (
            <ErrorState error={error} />
          ) : data.summary.by_model.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing recorded yet. Send a message in Chat and every model call appears here.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem]">
                <thead>
                  <tr className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    <th className="pb-2 pr-4 text-left font-medium">Model</th>
                    <th className="pb-2 pr-4 text-right font-medium">Calls</th>
                    <th className="pb-2 pr-4 text-right font-medium">Failures</th>
                    <th className="pb-2 pr-4 text-right font-medium">Mean latency</th>
                    <th className="pb-2 pr-4 text-right font-medium">Tokens / call</th>
                    <th className="pb-2 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.summary.by_model.map((row) => (
                    <ModelRow key={row.key} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {!isPending && !isError && data.summary.by_agent.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>By agent</CardTitle>
            <CardDescription>
              The same measurements grouped by who asked, which is where a prompt change shows up
              before anything else does.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem]">
                <thead>
                  <tr className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    <th className="pb-2 pr-4 text-left font-medium">Agent</th>
                    <th className="pb-2 pr-4 text-right font-medium">Calls</th>
                    <th className="pb-2 pr-4 text-right font-medium">Failures</th>
                    <th className="pb-2 pr-4 text-right font-medium">Mean latency</th>
                    <th className="pb-2 pr-4 text-right font-medium">Tokens / call</th>
                    <th className="pb-2 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.summary.by_agent.map((row) => (
                    <ModelRow key={row.key} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {!isPending && !isError ? (
        <p className="text-xs text-muted-foreground">{data.scope}</p>
      ) : null}
    </div>
  );
}
