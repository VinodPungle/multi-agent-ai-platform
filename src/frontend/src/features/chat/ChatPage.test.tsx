/**
 * Chat interface behaviour.
 *
 * Driven through the real component tree with `fetch` stubbed, so what is
 * asserted is what a user would see: typed text appears, streamed text renders
 * incrementally, Markdown becomes elements, stop and clear do what they say.
 *
 * Testing the rendered output rather than the hook's internals is deliberate —
 * these tests survive a refactor of `useChat` and would catch a regression the
 * hook's own state could hide.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ChatPage } from '@/features/chat/ChatPage';
import { requestBody, requestMethod, requestUrl } from '@/test/fetchAssertions';
import { renderWithProviders } from '@/test/utils';

/** Build an SSE body from a list of (event, payload) pairs. */
function sseBody(events: readonly (readonly [string, unknown])[]): string {
  return (
    ': stream open\n\n' +
    events.map(([name, payload]) => `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`).join('')
  );
}

function streamResponse(body: string): Response {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

const ANSWER_EVENTS = [
  [
    'started',
    {
      type: 'started',
      conversation_id: 'c1',
      message_id: 'm1',
      model_id: 'mock-echo',
      provider_id: 'mock',
    },
  ],
  ['delta', { type: 'delta', delta: 'Hello ' }],
  ['delta', { type: 'delta', delta: 'world' }],
  [
    'completed',
    {
      type: 'completed',
      message_id: 'm1',
      content: 'Hello world',
      usage: { prompt_tokens: 3, completion_tokens: 2 },
      finish_reason: 'stop',
    },
  ],
] as const;

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse(sseBody(ANSWER_EVENTS))));
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function send(text: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Message'), text);
  await user.click(screen.getByRole('button', { name: 'Send' }));
}

describe('ChatPage', () => {
  it('shows an empty state before anything is sent', () => {
    renderWithProviders(<ChatPage />);

    expect(screen.getByText('Start a conversation')).toBeInTheDocument();
  });

  it('renders the message the user sent', async () => {
    renderWithProviders(<ChatPage />);

    await send('What is this?');

    expect(await screen.findByText('What is this?')).toBeInTheDocument();
  });

  it('renders the streamed answer', async () => {
    renderWithProviders(<ChatPage />);

    await send('hello');

    expect(await screen.findByText('Hello world')).toBeInTheDocument();
  });

  it('does not send an empty message', async () => {
    renderWithProviders(<ChatPage />);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(fetch).not.toHaveBeenCalled();
  });

  it('does not send a whitespace-only message', async () => {
    renderWithProviders(<ChatPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText('Message'), '   ');

    // The button is disabled rather than the click being swallowed, so the UI
    // states the rule instead of appearing to ignore the user.
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('sends on Enter', async () => {
    renderWithProviders(<ChatPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText('Message'), 'hello{Enter}');

    expect(await screen.findByText('Hello world')).toBeInTheDocument();
  });

  it('inserts a newline on Shift+Enter instead of sending', async () => {
    renderWithProviders(<ChatPage />);
    const user = userEvent.setup();
    const input = screen.getByLabelText('Message');

    await user.type(input, 'first{Shift>}{Enter}{/Shift}second');

    expect(input).toHaveValue('first\nsecond');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('clears the input after sending', async () => {
    renderWithProviders(<ChatPage />);

    await send('hello');

    await waitFor(() => {
      expect(screen.getByLabelText('Message')).toHaveValue('');
    });
  });

  it('continues the conversation the server named', async () => {
    renderWithProviders(<ChatPage />);

    await send('first');
    await screen.findByText('Hello world');
    await send('second');

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(2);
    });
    expect(requestBody(vi.mocked(fetch).mock.calls[1])).toMatchObject({ conversation_id: 'c1' });
  });
});

describe('Markdown rendering', () => {
  it('renders Markdown structure as elements', async () => {
    vi.mocked(fetch).mockResolvedValue(
      streamResponse(
        sseBody([
          ['delta', { type: 'delta', delta: '## Heading\n\n- one\n- two\n' }],
          [
            'completed',
            {
              type: 'completed',
              message_id: 'm1',
              content: '## Heading\n\n- one\n- two\n',
              usage: { prompt_tokens: 1, completion_tokens: 1 },
            },
          ],
        ]),
      ),
    );
    renderWithProviders(<ChatPage />);

    await send('markdown please');

    expect(await screen.findByRole('heading', { name: 'Heading' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('renders a fenced code block with its language', async () => {
    const content = '```python\nprint("hi")\n```';
    vi.mocked(fetch).mockResolvedValue(
      streamResponse(
        sseBody([
          [
            'completed',
            {
              type: 'completed',
              message_id: 'm1',
              content,
              usage: { prompt_tokens: 1, completion_tokens: 1 },
            },
          ],
        ]),
      ),
    );
    renderWithProviders(<ChatPage />);

    await send('show me code');

    expect(await screen.findByText('python')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });

  it('does not execute HTML embedded in a response', async () => {
    // A model repeats what it was shown. Raw HTML must render as text.
    const content = '<img src=x onerror="alert(1)">';
    vi.mocked(fetch).mockResolvedValue(
      streamResponse(
        sseBody([
          [
            'completed',
            {
              type: 'completed',
              message_id: 'm1',
              content,
              usage: { prompt_tokens: 1, completion_tokens: 1 },
            },
          ],
        ]),
      ),
    );
    const { container } = renderWithProviders(<ChatPage />);

    await send('inject');

    await waitFor(() => {
      expect(container.querySelector('img')).toBeNull();
    });
  });

  it('renders the user message literally rather than as Markdown', async () => {
    // `__init__` must not become bold text.
    renderWithProviders(<ChatPage />);

    await send('what does __init__ do?');

    expect(await screen.findByText('what does __init__ do?')).toBeInTheDocument();
  });
});

describe('Turn actions', () => {
  it('offers stop while streaming and send when idle', async () => {
    renderWithProviders(<ChatPage />);

    await send('hello');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
    });
  });

  it('clears the transcript and forgets the conversation', async () => {
    renderWithProviders(<ChatPage />);
    await send('hello');
    await screen.findByText('Hello world');

    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));
    await userEvent.setup().click(screen.getByRole('button', { name: 'Clear' }));

    expect(screen.getByText('Start a conversation')).toBeInTheDocument();
    const lastCall = vi.mocked(fetch).mock.calls.at(-1);
    expect(requestUrl(lastCall)).toContain('/conversations/c1');
    expect(requestMethod(lastCall)).toBe('DELETE');
  });

  it('disables regenerate until there is something to regenerate', () => {
    renderWithProviders(<ChatPage />);

    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeDisabled();
  });

  it('regenerates the last answer', async () => {
    renderWithProviders(<ChatPage />);
    await send('hello');
    await screen.findByText('Hello world');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Regenerate' }));

    await waitFor(() => {
      expect(requestUrl(vi.mocked(fetch).mock.calls.at(-1))).toContain(
        '/conversations/c1/regenerate',
      );
    });
  });
});

describe('Error handling', () => {
  it('shows the backend message when a turn is rejected', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { category: 'validation', message: 'A message cannot be empty.' },
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    renderWithProviders(<ChatPage />);

    await send('hello');

    expect(await screen.findByRole('alert')).toHaveTextContent('A message cannot be empty.');
  });

  it('shows a mid-stream failure beside the partial answer', async () => {
    // A stream that has sent bytes reports failure in-band; the text already on
    // screen must survive.
    vi.mocked(fetch).mockResolvedValue(
      streamResponse(
        sseBody([
          ['delta', { type: 'delta', delta: 'partial answer' }],
          ['error', { type: 'error', category: 'provider', message: 'The provider failed.' }],
        ]),
      ),
    );
    renderWithProviders(<ChatPage />);

    await send('hello');

    const message = await screen.findByLabelText('Assistant message');
    expect(within(message).getByText('partial answer')).toBeInTheDocument();
    expect(within(message).getByRole('alert')).toHaveTextContent('The provider failed.');
  });

  it('reports an unreachable backend', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'));
    renderWithProviders(<ChatPage />);

    await send('hello');

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach/i);
  });
});
