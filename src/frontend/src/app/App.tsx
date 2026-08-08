/**
 * Application root.
 *
 * Milestone 01 renders a single Overview page proving the frontend reaches the
 * backend. Routing arrives with the second module in Milestone 02 — introducing
 * a router for one static page would be structure without purpose.
 */

import { PlatformCapabilitiesCard } from '@/features/platform-status/PlatformCapabilitiesCard';
import { PlatformStatusCard } from '@/features/platform-status/PlatformStatusCard';
import { AppShell } from '@/layouts/AppShell';

export function App() {
  return (
    <AppShell>
      <div className="flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Platform overview</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Repository foundation for the Enterprise Multi-Agent AI Platform. No agents, models or
            tools are registered yet — this milestone delivers the runtime, configuration,
            observability and delivery pipeline they will be built on.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <PlatformStatusCard />
          <PlatformCapabilitiesCard />
        </div>
      </div>
    </AppShell>
  );
}
