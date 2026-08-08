/**
 * Test helpers.
 *
 * Rendering through the real provider tree — with retries disabled — keeps
 * tests representative without making them slow or flaky.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';

import { ThemeProvider } from '@/app/theme';

/**
 * Build a query client suited to tests.
 *
 * Retries are off: with them on, a test asserting an error state waits for the
 * full backoff sequence before the state ever appears.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

/**
 * Render `ui` inside a fresh provider tree.
 *
 * Mirrors `AppProviders` exactly. A helper that provides less than the real
 * application does produces tests that pass against a tree the user never sees
 * — and a component that reads a missing context throws only in the test,
 * which reads as a component bug.
 */
export function renderWithProviders(ui: ReactElement): RenderResult {
  const queryClient = createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    );
  }

  return render(ui, { wrapper: Wrapper });
}

/** Build a `fetch` Response carrying `body` as JSON. */
export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}
