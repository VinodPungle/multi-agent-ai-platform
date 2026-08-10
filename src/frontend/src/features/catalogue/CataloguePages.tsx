/**
 * Discovery pages: Agents, Tools and Models.
 *
 * Each answers "what is registered in *this* deployment?" — which is a
 * different question from "what does the configuration say?", and the more
 * useful one. A tool switched off by a feature flag is absent here, and the
 * absence is the answer.
 *
 * The three share a layout because they are the same shape of question, and
 * sharing one keeps them consistent as any of them grows.
 */

import type { ReactNode } from 'react';

import { ApiError } from '@/api/client';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  formatPrice,
  formatTokenLimit,
  useAgents,
  useModels,
  useTools,
} from '@/features/catalogue/useCatalogue';

// --- Shared scaffolding ------------------------------------------------------

function PageHeading({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="max-w-2xl text-sm text-muted-foreground">{blurb}</p>
    </div>
  );
}

function ErrorState({ error }: { error: ApiError }) {
  return (
    <div role="alert" className="flex flex-col gap-2">
      <Badge variant="danger">Unavailable</Badge>
      <p className="text-sm text-muted-foreground">{error.message}</p>
      {error.correlationId ? (
        <p className="text-xs text-muted-foreground">
          Correlation ID: <code className="font-mono">{error.correlationId}</code>
        </p>
      ) : null}
    </div>
  );
}

/**
 * Render the four states every list here can be in.
 *
 * Loading, error, empty and populated — the bar the handbook sets for every
 * feature. The empty state takes a message rather than a generic one, because
 * "no agents" and "no tools" have different causes and different fixes.
 */
function CollectionState<T>({
  query,
  empty,
  children,
}: {
  query: { data?: T[]; error: ApiError | null; isPending: boolean; isError: boolean };
  empty: string;
  children: (items: T[]) => ReactNode;
}) {
  if (query.isPending) {
    return (
      <p className="text-sm text-muted-foreground" aria-live="polite">
        Loading…
      </p>
    );
  }
  if (query.isError && query.error) {
    return <ErrorState error={query.error} />;
  }
  const items = query.data ?? [];
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return <>{children(items)}</>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function Chips({ values, empty }: { values: readonly string[]; empty: string }) {
  if (values.length === 0) {
    return <span className="text-sm text-muted-foreground">{empty}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) => (
        <Badge key={value} variant="muted" className="font-mono">
          {value}
        </Badge>
      ))}
    </div>
  );
}

// --- Agents ------------------------------------------------------------------

export function AgentsPage() {
  const query = useAgents();

  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        title="Agents"
        blurb={
          'Every agent this deployment can run. An agent declares which model it prefers and ' +
          'which tools it may call; the runtime does everything else, which is why adding one ' +
          'is configuration rather than code.'
        }
      />

      <CollectionState query={query} empty="No agents are registered.">
        {(agents) => (
          <div className="grid gap-6 lg:grid-cols-2">
            {agents.map((agent) => (
              <Card key={agent.agent_id}>
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <CardTitle className="font-mono">{agent.agent_id}</CardTitle>
                    <Badge variant={agent.is_enabled ? 'success' : 'muted'}>
                      {agent.is_enabled ? 'Enabled' : 'Disabled'}
                    </Badge>
                  </div>
                  <CardDescription>{agent.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <dl className="flex flex-col gap-4">
                    <div className="grid grid-cols-2 gap-4">
                      <Field label="Provider">
                        <span className="font-mono">{agent.provider_id}</span>
                      </Field>
                      {/* "Preferred", not "model": routing policy may choose
                          another, and the response says which actually answered. */}
                      <Field label="Preferred model">
                        <span className="font-mono">{agent.model_id}</span>
                      </Field>
                    </div>
                    <Field label="Tools">
                      <Chips values={agent.tool_ids} empty="None — answers from the model alone" />
                    </Field>
                  </dl>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </CollectionState>
    </div>
  );
}

// --- Tools -------------------------------------------------------------------

export function ToolsPage() {
  const query = useTools();

  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        title="Tools"
        blurb={
          'Every tool the runtime can execute — local, remote, or hosted on an MCP server. ' +
          'Agents never call these directly: the runtime does, which is how authorisation, ' +
          'timeouts, retries, telemetry and budgets apply to all of them at once.'
        }
      />

      <CollectionState
        query={query}
        empty="No tools are registered. Tools are enabled by feature flags — an absent tool is switched off, not broken."
      >
        {(tools) => (
          <div className="grid gap-6 lg:grid-cols-2">
            {tools.map((tool) => (
              <Card key={tool.tool_id}>
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <CardTitle className="font-mono">{tool.tool_id}</CardTitle>
                    <Badge variant={tool.is_available ? 'success' : 'muted'}>
                      {tool.is_available ? 'Available' : 'Withdrawn'}
                    </Badge>
                  </div>
                  {/* This text is sent to the model. Showing it verbatim is the
                      point: it is what the model reads to decide when to call. */}
                  <CardDescription>{tool.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <dl className="flex flex-col gap-4">
                    <Field label="Parameters">
                      <Chips values={tool.parameters} empty="Takes no arguments" />
                    </Field>
                    <div className="grid grid-cols-2 gap-4">
                      <Field label="Timeout">{tool.timeout_seconds}s</Field>
                      <Field label="Retries">
                        {tool.max_attempts <= 1
                          ? // Not an omission: a tool that may have side effects
                            // is never retried automatically.
                            'None — may have side effects'
                          : `${tool.max_attempts - 1} after the first attempt`}
                      </Field>
                    </div>
                  </dl>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </CollectionState>
    </div>
  );
}

// --- Models ------------------------------------------------------------------

export function ModelsPage() {
  const query = useModels();

  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        title="Models"
        blurb={
          'The catalogue routing chooses from, built at startup by asking each registered ' +
          'provider what it serves — so it cannot advertise a model nothing can actually run. ' +
          'Prices are published rates, and they are where cost estimates come from.'
        }
      />

      <CollectionState
        query={query}
        empty="No models are registered, so no agent can answer. Check that a provider is enabled."
      >
        {(models) => (
          <div className="flex flex-col gap-4">
            {models.map((model) => (
              <Card key={`${model.provider_id}/${model.model_id}`}>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex flex-col gap-1">
                      <CardTitle className="font-mono">{model.model_id}</CardTitle>
                      <CardDescription>
                        {model.display_name} · served by{' '}
                        <span className="font-mono">{model.provider_id}</span>
                      </CardDescription>
                    </div>
                    <Badge variant={model.is_available ? 'success' : 'muted'}>
                      {model.is_available ? 'Routable' : 'Withdrawn'}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    <Field label="Context">{formatTokenLimit(model.max_context_tokens)}</Field>
                    <Field label="Max output">{formatTokenLimit(model.max_output_tokens)}</Field>
                    <Field label="Input price">
                      {formatPrice(model.input_cost_per_million_tokens, model.currency)}
                    </Field>
                    <Field label="Output price">
                      {formatPrice(model.output_cost_per_million_tokens, model.currency)}
                    </Field>
                  </dl>
                  <div className="mt-4">
                    <Field label="Capabilities">
                      {/* Routing filters on these, never on the provider's name —
                          which is what lets a new provider work unchanged. */}
                      <Chips values={model.capabilities} empty="None declared" />
                    </Field>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </CollectionState>
    </div>
  );
}
