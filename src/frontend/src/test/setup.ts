/**
 * Vitest setup, applied before every test file.
 *
 * Establishes the same two guarantees as the backend suite: no network access,
 * and no state shared between tests.
 */

import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

// Set before any module reads `import.meta.env`. Without this, `config/env.ts`
// throws at import time and every test file fails to collect.
vi.stubEnv('VITE_API_BASE_URL', 'http://api.test');
vi.stubEnv('VITE_APP_NAME', 'Test Platform');

beforeEach(() => {
  // A test that forgets to stub `fetch` must fail loudly rather than reach the
  // network and pass or hang depending on what is running locally.
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
    throw new Error('Unexpected network call. Stub `fetch` explicitly in the test.');
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
