/**
 * Vite configuration.
 *
 * Environment variables are read from the repository root rather than from this
 * directory, so backend and frontend share one `.env` file. Two files would
 * drift, and a developer would have to remember which one holds what.
 */

import { fileURLToPath, URL } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
// `vitest/config` re-exports Vite's `defineConfig` widened with the `test`
// block, so build and test configuration stay in one file.
import { defineConfig } from 'vitest/config';

const repositoryRoot = fileURLToPath(new URL('../../', import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],

  envDir: repositoryRoot,

  resolve: {
    alias: {
      // Absolute imports. Relative chains like `../../../api/client` obscure the
      // dependency direction and break silently when a file is moved.
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    // Bind on all interfaces so the dev server is reachable from outside its
    // container. Compose maps it to localhost.
    host: true,
    port: 5173,
    strictPort: true,
    watch: {
      // Bind-mounted volumes on Windows and macOS do not deliver filesystem
      // events into a Linux container; polling is what makes hot reload work
      // under Compose.
      usePolling: process.env.VITE_USE_POLLING === 'true',
    },
  },

  preview: {
    host: true,
    port: 4173,
    strictPort: true,
  },

  build: {
    outDir: 'dist',
    sourcemap: true,
    // Fails the build rather than shipping a bundle that silently crossed a
    // performance budget.
    chunkSizeWarningLimit: 600,
  },

  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx'],
    },
  },
});
