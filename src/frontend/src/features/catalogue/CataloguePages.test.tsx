/**
 * The discovery pages.
 *
 * These replaced four disabled nav placeholders, so the thing most worth
 * asserting is that each page renders real registry data rather than looking
 * plausible while empty — and that the states which say *why* something is
 * missing actually say it.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { AgentsPage, ModelsPage, ToolsPage } from '@/features/catalogue/CataloguePages';
import { formatPrice, formatTokenLimit } from '@/features/catalogue/useCatalogue';
import { jsonResponse, renderWithProviders } from '@/test/utils';

function stub(payload: unknown, status = 200): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
    Promise.resolve(jsonResponse(payload, { status })),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

const AGENTS = [
  {
    agent_id: 'chat-agent',
    name: 'Chat Agent',
    description: 'Answers questions.',
    version: '1.0',
    owner: null,
    provider_id: 'azure-foundry',
    model_id: 'fw-kimi-k3',
    tool_ids: ['internet-search', 'knowledge-search'],
    temperature: 0.2,
    max_output_tokens: 4096,
    is_enabled: true,
  },
];

const TOOLS = [
  {
    tool_id: 'knowledge-search',
    description: "Search the organisation's own documents.",
    version: '1.0',
    owner: 'platform-team',
    parameters: ['query', 'max_passages'],
    required_parameters: ['query'],
    timeout_seconds: 15,
    max_attempts: 2,
    is_available: true,
  },
  {
    tool_id: 'mcp.directory.lookup',
    description: 'Look someone up.',
    version: '1.0',
    owner: 'mcp:directory',
    parameters: ['name'],
    required_parameters: ['name'],
    timeout_seconds: 30,
    max_attempts: 1,
    is_available: true,
  },
];

const MODELS = [
  {
    model_id: 'fw-kimi-k3',
    provider_id: 'azure-foundry',
    display_name: 'FW Kimi K3',
    version: '1',
    capabilities: ['cost_reporting', 'streaming', 'tool_calling'],
    max_context_tokens: 128000,
    max_output_tokens: 4096,
    input_cost_per_million_tokens: '0.60',
    output_cost_per_million_tokens: '2.40',
    currency: 'USD',
    is_available: true,
  },
];

describe('formatPrice', () => {
  it('says a model is not priced rather than showing it as free', () => {
    // A model with no configured price still costs something; the platform has
    // simply not been told what. "$0.00" would make every derived cost wrong.
    expect(formatPrice('0')).toBe('Not priced');
  });

  it('shows a configured rate per million tokens', () => {
    expect(formatPrice('0.6')).toBe('$0.60/M');
  });
});

describe('formatTokenLimit', () => {
  it('compacts context windows', () => {
    expect(formatTokenLimit(128000)).toBe('128K');
    expect(formatTokenLimit(1000000)).toBe('1M');
    expect(formatTokenLimit(512)).toBe('512');
  });
});

describe('AgentsPage', () => {
  it('lists the registered agents with the model they prefer', async () => {
    stub(AGENTS);
    renderWithProviders(<AgentsPage />);

    expect(await screen.findByText('chat-agent')).toBeInTheDocument();
    expect(screen.getByText('fw-kimi-k3')).toBeInTheDocument();
  });

  it('shows the tools an agent declares', async () => {
    stub(AGENTS);
    renderWithProviders(<AgentsPage />);

    expect(await screen.findByText('knowledge-search')).toBeInTheDocument();
  });

  it('says an agent has no tools rather than showing an empty gap', async () => {
    stub([{ ...AGENTS[0], tool_ids: [] }]);
    renderWithProviders(<AgentsPage />);

    expect(await screen.findByText(/answers from the model alone/i)).toBeInTheDocument();
  });

  it('reports an unreachable backend instead of an empty page', async () => {
    stub({ detail: 'boom' }, 500);
    renderWithProviders(<AgentsPage />);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

describe('ToolsPage', () => {
  it('lists tools with their parameters', async () => {
    stub(TOOLS);
    renderWithProviders(<ToolsPage />);

    expect(await screen.findByText('knowledge-search')).toBeInTheDocument();
    expect(screen.getByText('max_passages')).toBeInTheDocument();
  });

  it('explains why a tool is not retried rather than showing a bare zero', async () => {
    stub(TOOLS);
    renderWithProviders(<ToolsPage />);

    // The MCP tool allows one attempt: a remote tool may have side effects.
    expect(await screen.findByText(/may have side effects/i)).toBeInTheDocument();
  });

  it('says an absent tool is switched off, not broken', async () => {
    stub([]);
    renderWithProviders(<ToolsPage />);

    expect(await screen.findByText(/switched off, not broken/i)).toBeInTheDocument();
  });
});

describe('ModelsPage', () => {
  it('lists the catalogue with limits and prices', async () => {
    stub(MODELS);
    renderWithProviders(<ModelsPage />);

    expect(await screen.findByText('fw-kimi-k3')).toBeInTheDocument();
    expect(screen.getByText('128K')).toBeInTheDocument();
    expect(screen.getByText('$0.60/M')).toBeInTheDocument();
  });

  it('shows declared capabilities, which is what routing filters on', async () => {
    stub(MODELS);
    renderWithProviders(<ModelsPage />);

    expect(await screen.findByText('tool_calling')).toBeInTheDocument();
  });

  it('says an empty catalogue means no agent can answer', async () => {
    stub([]);
    renderWithProviders(<ModelsPage />);

    expect(await screen.findByText(/no agent can answer/i)).toBeInTheDocument();
  });
});
