/**
 * Browser entry point.
 *
 * Configuration is imported before anything renders, so an invalid environment
 * fails immediately and visibly rather than partway through the first user
 * interaction.
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from '@/app/App';
import { AppProviders } from '@/app/providers';
import '@/styles/globals.css';

const container = document.getElementById('root');

if (!container) {
  throw new Error('Root element #root is missing from index.html.');
}

createRoot(container).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
);
