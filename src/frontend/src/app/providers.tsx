/**
 * Application-wide providers.
 *
 * Kept separate from `App` so tests can mount components inside a fresh, fully
 * configured provider tree without importing the whole application.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { createQueryClient } from '@/app/queryClient';

export function AppProviders({ children }: { children: ReactNode }) {
  // `useState` with an initialiser, not `useMemo`: this guarantees exactly one
  // client per mount even under React 19's strict-mode double render.
  const [queryClient] = useState(createQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
