/**
 * Contracts shared with the backend API.
 *
 * Declared as Zod schemas rather than bare TypeScript types so that responses
 * are validated at runtime, not merely asserted at compile time. A backend that
 * changes shape then fails at the boundary with a clear message, instead of
 * producing `undefined` somewhere deep in a component.
 */

import { z } from 'zod';

/** Mirrors `agent_platform_sdk.types.enums.HealthStatus`. */
export const healthStatusSchema = z.enum(['healthy', 'degraded', 'unhealthy', 'unknown']);
export type HealthStatus = z.infer<typeof healthStatusSchema>;

export const componentHealthSchema = z.object({
  name: z.string(),
  status: healthStatusSchema,
  detail: z.string().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
});
export type ComponentHealth = z.infer<typeof componentHealthSchema>;

export const healthReportSchema = z.object({
  status: healthStatusSchema,
  components: z.array(componentHealthSchema),
});

/** Response of `GET /health`. */
export const healthResponseSchema = z.object({
  status: healthStatusSchema,
  name: z.string(),
  version: z.string(),
  environment: z.string(),
  report: healthReportSchema,
});
export type HealthResponse = z.infer<typeof healthResponseSchema>;

/** Response of `GET /api/v1/info`. */
export const platformInfoSchema = z.object({
  name: z.string(),
  version: z.string(),
  environment: z.string(),
  api_version: z.string(),
  features: z.record(z.string(), z.boolean()),
});
export type PlatformInfo = z.infer<typeof platformInfoSchema>;

/** Mirrors `agent_platform_sdk.types.enums.ErrorCategory`. */
export const errorCategorySchema = z.enum([
  'configuration',
  'validation',
  'provider',
  'network',
  'tool',
  'memory',
  'timeout',
  'policy_violation',
  'not_found',
  'unexpected',
]);
export type ErrorCategory = z.infer<typeof errorCategorySchema>;

/** The error envelope every failing endpoint returns. */
export const errorResponseSchema = z.object({
  error: z.object({
    category: errorCategorySchema,
    message: z.string(),
    correlation_id: z.string().nullable().optional(),
    fields: z
      .array(z.object({ location: z.string(), message: z.string() }))
      .optional()
      .default([]),
  }),
});
export type ErrorResponse = z.infer<typeof errorResponseSchema>;
