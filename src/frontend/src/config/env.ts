/**
 * Typed, validated runtime configuration.
 *
 * The backend validates its configuration at startup and refuses to run when it
 * is wrong. The frontend does the same, for the same reason: a missing API base
 * URL should surface as one clear message at boot, not as a stream of confusing
 * network failures once a user starts clicking.
 *
 * Only `VITE_`-prefixed variables reach browser code. A secret placed behind
 * that prefix is embedded verbatim in the shipped bundle, so nothing sensitive
 * may ever be read here.
 */

import { z } from 'zod';

const envSchema = z.object({
  /** Base URL of the platform API. No trailing slash — the client appends paths. */
  VITE_API_BASE_URL: z
    .string()
    .url('VITE_API_BASE_URL must be an absolute URL, e.g. http://localhost:8000')
    .transform((value) => value.replace(/\/+$/, '')),

  /** Name shown in the shell. Configurable so a deployment can be branded. */
  VITE_APP_NAME: z.string().min(1).default('Multi-Agent AI Platform'),
});

export type AppEnvironment = z.infer<typeof envSchema>;

function loadEnvironment(): AppEnvironment {
  const result = envSchema.safeParse(import.meta.env);

  if (!result.success) {
    const problems = result.error.issues
      .map((issue) => `  - ${issue.path.join('.')}: ${issue.message}`)
      .join('\n');

    // Thrown at module load, so the failure is immediate and unambiguous rather
    // than deferred to the first request that happens to need the value.
    throw new Error(
      `Frontend configuration is invalid and the application cannot start.\n${problems}\n` +
        'Copy .env.example to .env at the repository root and set the missing values.',
    );
  }

  return result.data;
}

export const env: AppEnvironment = loadEnvironment();
