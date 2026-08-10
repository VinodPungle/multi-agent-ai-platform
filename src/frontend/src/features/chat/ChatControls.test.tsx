/**
 * The chat settings panel and history sidebar.
 *
 * The behaviour worth pinning is the one that is easy to get subtly wrong:
 * "unset" and "zero" are different things. A temperature of 0 is a deliberate
 * request for determinism, so a control that defaulted to a number would
 * override the agent on every turn while appearing to do nothing.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ChatHistory } from '@/features/chat/ChatHistory';
import { ChatSettings } from '@/features/chat/ChatSettings';
import { jsonResponse, renderWithProviders } from '@/test/utils';
import type { GenerationOptions } from '@/features/chat/useChat';

const MODELS = [
  {
    model_id: 'fw-kimi-k3',
    provider_id: 'azure-foundry',
    display_name: 'FW Kimi K3',
    version: '1',
    capabilities: ['streaming'],
    max_context_tokens: 128000,
    max_output_tokens: 4096,
    input_cost_per_million_tokens: '99.95',
    output_cost_per_million_tokens: '420.86',
    currency: 'INR',
    is_available: true,
  },
  {
    model_id: 'retired-model',
    provider_id: 'azure-foundry',
    display_name: 'Retired',
    version: '1',
    capabilities: [],
    max_context_tokens: 8000,
    max_output_tokens: 1024,
    input_cost_per_million_tokens: '0',
    output_cost_per_million_tokens: '0',
    currency: 'INR',
    is_available: false,
  },
];

function stub(payload: unknown): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(jsonResponse(payload)));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ChatSettings', () => {
  it('shows the model selector without anything having to be opened', () => {
    // The regression this pins: the selector shipped inside the collapsed
    // panel, where nobody found it.
    stub(MODELS);
    renderWithProviders(<ChatSettings value={{}} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Model')).toBeInTheDocument();
  });

  it('keeps temperature behind the toggle', () => {
    stub(MODELS);
    renderWithProviders(<ChatSettings value={{}} onChange={vi.fn()} />);

    expect(screen.queryByLabelText('Temperature')).not.toBeInTheDocument();
  });

  it('offers the agent default rather than preselecting a model', async () => {
    stub(MODELS);
    renderWithProviders(<ChatSettings value={{}} onChange={vi.fn()} />);

    expect(await screen.findByRole('option', { name: /Agent default/ })).toBeInTheDocument();
  });

  it('does not offer a model that has been withdrawn from routing', async () => {
    stub(MODELS);
    renderWithProviders(<ChatSettings value={{}} onChange={vi.fn()} />);

    await screen.findByRole('option', { name: 'fw-kimi-k3' });

    expect(screen.queryByRole('option', { name: 'retired-model' })).not.toBeInTheDocument();
  });

  it('says so when the catalogue lists no usable model', async () => {
    // A lone "Agent default" option looks like a working control with nothing
    // to pick, rather than a catalogue that failed to load.
    stub([]);
    renderWithProviders(<ChatSettings value={{}} onChange={vi.fn()} />);

    expect(await screen.findByText(/No models listed/i)).toBeInTheDocument();
  });

  it('shows nothing overridden when every control is at its default', () => {
    stub(MODELS);
    renderWithProviders(<ChatSettings value={{}} onChange={vi.fn()} />);

    expect(screen.queryByText(/override/)).not.toBeInTheDocument();
  });

  it('counts a temperature of zero as an override', () => {
    // The case a truthiness check gets wrong: 0 is a deliberate setting, not
    // an absent one.
    stub(MODELS);
    const value: GenerationOptions = { temperature: 0 };
    renderWithProviders(<ChatSettings value={value} onChange={vi.fn()} />);

    expect(screen.getByText('1 override')).toBeInTheDocument();
  });

  it('resets every override at once', async () => {
    stub(MODELS);
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <ChatSettings value={{ temperature: 0, modelId: 'fw-kimi-k3' }} onChange={onChange} />,
    );

    await user.click(screen.getByRole('button', { name: 'Reset' }));

    expect(onChange).toHaveBeenCalledWith({});
  });
});

describe('ChatHistory', () => {
  const CONVERSATIONS = {
    conversations: [
      { conversation_id: 'c1', message_count: 4, preview: 'how do budgets work' },
      { conversation_id: 'c2', message_count: 2, preview: '' },
    ],
  };

  it('lists past conversations by how they started', async () => {
    stub(CONVERSATIONS);
    renderWithProviders(<ChatHistory currentConversationId={null} onOpen={vi.fn()} />);

    expect(await screen.findByText('how do budgets work')).toBeInTheDocument();
  });

  it('labels a conversation with no user message rather than showing a blank row', async () => {
    stub(CONVERSATIONS);
    renderWithProviders(<ChatHistory currentConversationId={null} onOpen={vi.fn()} />);

    expect(await screen.findByText('Untitled conversation')).toBeInTheDocument();
  });

  it('marks the conversation currently open', async () => {
    stub(CONVERSATIONS);
    renderWithProviders(<ChatHistory currentConversationId="c1" onOpen={vi.fn()} />);

    const current = await screen.findByText('how do budgets work');
    expect(current.closest('button')).toHaveAttribute('aria-current', 'true');
  });

  it('opens a conversation when its entry is clicked', async () => {
    stub(CONVERSATIONS);
    const onOpen = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<ChatHistory currentConversationId={null} onOpen={onOpen} />);

    await user.click(await screen.findByText('how do budgets work'));

    expect(onOpen).toHaveBeenCalledWith('c1');
  });

  it('refuses to switch conversation mid-stream', async () => {
    // Swapping the thread under an in-flight answer would attach it to the
    // wrong conversation.
    stub(CONVERSATIONS);
    renderWithProviders(<ChatHistory currentConversationId={null} onOpen={vi.fn()} disabled />);

    const entry = await screen.findByText('how do budgets work');
    expect(entry.closest('button')).toBeDisabled();
  });

  it('says history is unavailable without claiming chat is broken', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    renderWithProviders(<ChatHistory currentConversationId={null} onOpen={vi.fn()} />);

    expect(await screen.findByText(/chat still works/i)).toBeInTheDocument();
  });

  it('explains an empty list rather than showing nothing', async () => {
    stub({ conversations: [] });
    renderWithProviders(<ChatHistory currentConversationId={null} onOpen={vi.fn()} />);

    expect(await screen.findByText(/No past conversations/i)).toBeInTheDocument();
  });
});
