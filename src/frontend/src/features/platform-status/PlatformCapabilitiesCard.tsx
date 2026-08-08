/**
 * Effective feature flags.
 *
 * Makes visible the principle that capabilities are enabled by configuration,
 * never by code change.
 *
 * Every capability listed here has now shipped, so an off flag is a deliberate
 * choice rather than pending work. The caption says so: labelling a disabled
 * capability with a milestone that has already passed reads as "broken" when it
 * means "switched off".
 */

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { usePlatformInfo } from '@/features/platform-status/usePlatformStatus';

function humanise(flag: string): string {
  return flag.replace(/_/g, ' ').replace(/^./, (character) => character.toUpperCase());
}

export function PlatformCapabilitiesCard() {
  const { data, isPending, isError } = usePlatformInfo();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Capabilities</CardTitle>
        <CardDescription>
          Enabled entirely by configuration. No capability requires a code change.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <p className="text-sm text-muted-foreground" aria-live="polite">
            Loading…
          </p>
        ) : isError ? (
          <p className="text-sm text-muted-foreground" role="alert">
            Capabilities are unavailable while the API cannot be reached.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {Object.entries(data.features).map(([flag, enabled]) => (
              <li
                key={flag}
                className="flex items-center justify-between gap-4 py-2 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{humanise(flag)}</p>
                  {!enabled ? (
                    // One string rather than interpolated JSX so it renders as a
                    // single text node — split nodes are invisible to both screen
                    // readers and text queries.
                    <p className="text-xs text-muted-foreground">{'Disabled by configuration'}</p>
                  ) : null}
                </div>
                <Badge variant={enabled ? 'success' : 'muted'}>
                  {enabled ? 'Enabled' : 'Disabled'}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
