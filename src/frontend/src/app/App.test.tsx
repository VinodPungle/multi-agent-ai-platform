/**
 * Application shell rendering.
 *
 * Milestone 01 acceptance criteria: "Frontend renders application shell" and
 * "Frontend renders without console errors".
 *
 * Covers the states the handbook requires of every feature: loading, populated,
 * empty and error.
 */

import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '@/app/App';
import { jsonResponse, renderWithProviders } from '@/test/utils';

const healthPayload = {
  status: 'healthy',
  name: 'multi-agent-ai-platform',
  version: '0.1.0',
  environment: 'development',
  report: {
    status: 'healthy',
    components: [
      {
        name: 'configuration',
        status: 'healthy',
        detail: 'environment=development',
        latency_ms: 0.42,
      },
    ],
  },
};

const infoPayload = {
  name: 'multi-agent-ai-platform',
  version: '0.1.0',
  environment: 'development',
  api_version: 'v1',
  features: {
    streaming: false,
    memory: false,
    search: false,
    evaluation: false,
    cost_tracking: false,
  },
};

/** Resolve a `fetch` input to its URL string, whatever form it arrived in. */
function urlOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

/** Route stubbed responses by path, so both cards can be exercised together. */
/**
 * Default cost payload.
 *
 * The overview renders the spend card, so `App` now calls the analytics
 * endpoint. Without a stub it falls through to the catch-all below and the
 * resulting failure surfaces in *other* cards' error assertions — which is
 * exactly what happened when the card was first added.
 */
const costsPayload = {
  summary: {
    overall: {
      invocations: 0,
      failures: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      estimated_cost: '0',
      average_latency_ms: 0,
    },
    by_model: [],
    by_provider: [],
    by_agent: [],
  },
  scope: 'This process since startup.',
};

function stubApi(overrides: { health?: Response; info?: Response; costs?: Response } = {}) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = urlOf(input);
    if (url.includes('/analytics/costs')) {
      return Promise.resolve(overrides.costs ?? jsonResponse(costsPayload));
    }
    if (url.includes('/health')) {
      return Promise.resolve(overrides.health ?? jsonResponse(healthPayload));
    }
    if (url.includes('/api/v1/info')) {
      return Promise.resolve(overrides.info ?? jsonResponse(infoPayload));
    }
    return Promise.reject(new Error(`Unexpected request to ${url}`));
  });
}

describe('App shell', () => {
  beforeEach(() => {
    stubApi();
  });

  it('renders the platform name and heading', () => {
    renderWithProviders(<App />);

    expect(screen.getByRole('heading', { name: /platform overview/i })).toBeInTheDocument();
    expect(screen.getByText('Test Platform')).toBeInTheDocument();
  });

  it('exposes a skip link for keyboard users', () => {
    renderWithProviders(<App />);

    expect(screen.getByRole('link', { name: /skip to content/i })).toBeInTheDocument();
  });

  it('every module in the navigation is reachable', () => {
    // This assertion used to be its opposite: modules not yet built rendered
    // as `aria-disabled` placeholders, and the test named whichever was still
    // to come. Milestone 09 delivered the last of them, so there is nothing
    // left to be disabled and the check inverts.
    //
    // Worth keeping in this form. A placeholder reintroduced here fails the
    // test, which is the moment to ask whether shipping a dead nav item is
    // really better than shipping nothing.
    renderWithProviders(<App />);

    for (const label of ['Overview', 'Chat', 'Agents', 'Tools', 'Models', 'Evaluations', 'Cost']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument();
    }
  });

  it('links to the modules that have been delivered', () => {
    renderWithProviders(<App />);

    expect(screen.getByRole('link', { name: 'Chat' })).toHaveAttribute('href', '/chat');
  });

  it('renders without writing to the console', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    renderWithProviders(<App />);
    // Both cards must have settled; asserting before then would pass trivially.
    await screen.findAllByText('Healthy');
    await screen.findByText('Streaming');

    expect(consoleError).not.toHaveBeenCalled();
    expect(consoleWarn).not.toHaveBeenCalled();
  });
});

describe('backend status', () => {
  it('shows a loading state before the response arrives', () => {
    stubApi();

    renderWithProviders(<App />);

    expect(screen.getByText('Checking…')).toBeInTheDocument();
  });

  it('renders health once loaded', async () => {
    stubApi();

    renderWithProviders(<App />);

    // Twice: once for the overall status, once for the `configuration` component.
    expect(await screen.findAllByText('Healthy')).toHaveLength(2);
    expect(screen.getByText('configuration')).toBeInTheDocument();
    expect(screen.getByText('environment=development')).toBeInTheDocument();
    expect(screen.getByText('0.4 ms')).toBeInTheDocument();
  });

  it('renders an empty state when no components are registered', async () => {
    stubApi({
      health: jsonResponse({
        ...healthPayload,
        report: { status: 'healthy', components: [] },
      }),
    });

    renderWithProviders(<App />);

    expect(await screen.findByText(/no components are registered yet/i)).toBeInTheDocument();
  });

  it('renders an error state with the correlation id when the API fails', async () => {
    stubApi({
      health: jsonResponse(
        {
          error: {
            category: 'unexpected',
            message: 'An unexpected error occurred.',
            correlation_id: 'corr-visible-to-user',
            fields: [],
          },
        },
        { status: 500 },
      ),
    });

    renderWithProviders(<App />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('An unexpected error occurred.');
    // Quoting the id is what makes a user's report traceable server-side.
    expect(alert).toHaveTextContent('corr-visible-to-user');
  });

  it('reports a degraded platform distinctly from an unhealthy one', async () => {
    stubApi({
      health: jsonResponse({
        ...healthPayload,
        status: 'degraded',
        report: {
          status: 'degraded',
          components: [{ name: 'search', status: 'degraded', detail: null, latency_ms: null }],
        },
      }),
    });

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getAllByText('Degraded')).toHaveLength(2);
    });
  });
});

describe('capabilities', () => {
  it('lists every feature flag with its state', async () => {
    stubApi();

    renderWithProviders(<App />);

    expect(await screen.findByText('Streaming')).toBeInTheDocument();
    expect(screen.getByText('Cost tracking')).toBeInTheDocument();
    expect(screen.getAllByText('Disabled')).toHaveLength(5);
  });

  it('says a disabled capability is switched off, not unbuilt', async () => {
    stubApi();

    renderWithProviders(<App />);

    // Every capability has shipped, so an off flag is a deployment choice.
    // Naming a milestone that has already passed reads as "broken".
    expect(await screen.findAllByText('Disabled by configuration')).toHaveLength(5);
  });

  it('degrades gracefully when the info endpoint fails', async () => {
    stubApi({ info: jsonResponse({ detail: 'boom' }, { status: 500 }) });

    renderWithProviders(<App />);

    expect(
      await screen.findByText(/capabilities are unavailable while the api cannot be reached/i),
    ).toBeInTheDocument();
  });
});
