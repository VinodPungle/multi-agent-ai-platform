/**
 * Live backend connectivity and health.
 *
 * This is the component that makes Milestone 01 verifiable in a browser: it
 * proves the frontend reaches the backend, that the contract validates, and
 * that loading, empty and error states all exist — the quality bar the handbook
 * sets for every frontend feature.
 */

import { ApiError } from '@/api/client';
import { Badge, type BadgeVariant } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { usePlatformHealth } from '@/features/platform-status/usePlatformStatus';
import type { HealthStatus } from '@/api/types';

const statusVariant: Record<HealthStatus, BadgeVariant> = {
  healthy: 'success',
  degraded: 'warning',
  unhealthy: 'danger',
  unknown: 'muted',
};

const statusLabel: Record<HealthStatus, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  unhealthy: 'Unhealthy',
  unknown: 'Unknown',
};

function ErrorState({ error }: { error: ApiError }) {
  return (
    <div role="alert" className="flex flex-col gap-2">
      <Badge variant="danger">Unavailable</Badge>
      <p className="text-sm text-muted-foreground">{error.message}</p>
      {error.correlationId ? (
        // Surfaced deliberately: this is the identifier that lets an operator
        // find the exact server-side trace for what the user just saw.
        <p className="text-xs text-muted-foreground">
          Correlation ID: <code className="font-mono">{error.correlationId}</code>
        </p>
      ) : null}
    </div>
  );
}

export function PlatformStatusCard() {
  const { data, error, isPending, isError } = usePlatformHealth();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Backend status</CardTitle>
        <CardDescription>Live health of the platform API and its components.</CardDescription>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <p className="text-sm text-muted-foreground" aria-live="polite">
            Checking…
          </p>
        ) : isError ? (
          <ErrorState error={error} />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusVariant[data.status]}>{statusLabel[data.status]}</Badge>
              <span className="text-sm text-muted-foreground">
                {data.name} v{data.version} · {data.environment}
              </span>
            </div>

            {data.report.components.length === 0 ? (
              <p className="text-sm text-muted-foreground">No components are registered yet.</p>
            ) : (
              <ul className="flex flex-col divide-y divide-border">
                {data.report.components.map((component) => (
                  <li
                    key={component.name}
                    className="flex items-center justify-between gap-4 py-2 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{component.name}</p>
                      {component.detail ? (
                        <p className="truncate text-xs text-muted-foreground">{component.detail}</p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {typeof component.latency_ms === 'number' ? (
                        <span className="font-mono text-xs text-muted-foreground">
                          {component.latency_ms.toFixed(1)} ms
                        </span>
                      ) : null}
                      <Badge variant={statusVariant[component.status]}>
                        {statusLabel[component.status]}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
