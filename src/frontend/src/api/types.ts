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

/**
 * Cost and usage totals.
 *
 * `estimated_cost` is a **string**, not a number, and that is deliberate on
 * both sides of the wire. The backend sums money as `Decimal` precisely so
 * fractions of a cent do not drift; parsing it into a JavaScript `number` here
 * would reintroduce the error the moment it is added to anything. It is
 * formatted for display and never used in arithmetic.
 */
export const usageTotalsSchema = z.object({
  invocations: z.number().int().nonnegative(),
  failures: z.number().int().nonnegative(),
  prompt_tokens: z.number().int().nonnegative(),
  completion_tokens: z.number().int().nonnegative(),
  // A string on the wire, verified: pydantic serialises `Decimal` to a JSON
  // string, which is what preserves the precision the backend sums with.
  // Kept as a string here for the same reason — see `formatCost`.
  estimated_cost: z.string(),
  average_latency_ms: z.number().nonnegative(),
});

export const costBreakdownSchema = z.object({
  key: z.string(),
  usage: usageTotalsSchema,
});

export const costSummarySchema = z.object({
  overall: usageTotalsSchema,
  by_model: z.array(costBreakdownSchema),
  by_provider: z.array(costBreakdownSchema),
  by_agent: z.array(costBreakdownSchema),
});

export const costSummaryResponseSchema = z.object({
  summary: costSummarySchema,
  /** What the numbers cover. Rendered, never hidden — see the analytics card. */
  scope: z.string(),
});

export type UsageTotals = z.infer<typeof usageTotalsSchema>;
export type CostBreakdown = z.infer<typeof costBreakdownSchema>;
export type CostSummary = z.infer<typeof costSummarySchema>;
export type CostSummaryResponse = z.infer<typeof costSummaryResponseSchema>;
