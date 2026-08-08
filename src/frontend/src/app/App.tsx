/**
 * Application root and routing.
 *
 * Milestone 02 adds the second module, so routing now earns its place —
 * Milestone 01 deliberately had none, because a router for one static page is
 * structure without purpose.
 *
 * `BrowserRouter` rather than `HashRouter`: the deployment serves an SPA
 * fallback (see `docker/nginx.conf`), so clean paths work on refresh and are
 * what a link shared with a colleague should look like.
 */

import { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { PlatformCapabilitiesCard } from '@/features/platform-status/PlatformCapabilitiesCard';
import { PlatformStatusCard } from '@/features/platform-status/PlatformStatusCard';
import { AppShell } from '@/layouts/AppShell';

/**
 * Chat is loaded on demand.
 *
 * Its Markdown renderer and syntax highlighter are together larger than the
 * rest of the application, and a user who only opens the overview should not
 * download a highlighter for forty languages to read two status cards. The
 * chunk is fetched when the route is first visited.
 */
const ChatPage = lazy(() =>
  import('@/features/chat/ChatPage').then((module) => ({ default: module.ChatPage })),
);

export function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/chat" element={<ChatPage />} />
            {/* Any unknown path returns to the overview rather than showing a
                blank page. `replace` keeps the bad URL out of history. */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AppShell>
    </BrowserRouter>
  );
}

function RouteFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="py-12 text-center text-sm text-muted-foreground"
    >
      Loading…
    </div>
  );
}

function OverviewPage() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Platform overview</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Enterprise Multi-Agent AI Platform. Chat runs against a mock provider with session memory;
          Azure AI Foundry and Gemma 4 arrive in Milestone 05.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <PlatformStatusCard />
        <PlatformCapabilitiesCard />
      </div>
    </div>
  );
}
