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
import { jsonResponse, renderWithProviders } from '@/test/utils';

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

/**
 * The page makes more than one request now.
 *
 * Besides the chat stream it loads the conversation history and the model
 * catalogue, so a single `mockResolvedValue` no longer works: one `Response`
 * body can only be read once, and whichever query got there first consumed it.
 *
 * Routing by URL also keeps the chat assertions honest — `chatCalls()` counts
 * only what was sent to the chat endpoints, so "sent one message" stays a
 * statement about messages rather than about HTTP traffic.
 */
function routeFetch(chatResponse: () => Response): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrlOf(input);
      if (url.includes('/chat/conversations') && !url.includes('regenerate')) {
        return Promise.resolve(jsonResponse({ conversations: [] }));
      }
      if (url.includes('/api/v1/models')) {
        return Promise.resolve(jsonResponse([]));
      }
      return Promise.resolve(chatResponse());
    }),
  );
}

function requestUrlOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

/** Calls that actually went to a chat endpoint. */
function chatCalls(): unknown[][] {
  return vi.mocked(fetch).mock.calls.filter((call) => {
    const url = requestUrlOf(call[0]);
    // The history list lives under `/chat/conversations` too, and carries a
    // query string — so matching the path alone counts a sidebar refresh as a
    // sent message, which is how "sent one message" became "made five
    // requests". Anything with `?` or ending there is the list, not a turn.
    const isHistoryList = /\/chat\/conversations(\?|$)/.test(url);
    return url.includes('/chat/') && !isHistoryList;
  });
}

beforeEach(() => {
  routeFetch(() => streamResponse(sseBody(ANSWER_EVENTS)));
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

    expect(chatCalls()).toHaveLength(0);
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
    expect(chatCalls()).toHaveLength(0);
  });

  it('clears the input after sending', async () => {
    renderWithProviders(<ChatPage />);

    await send('hello');

    await waitFor(() => {
      expect(screen.getByLabelText('Message')).toHaveValue('');
    });
  });

  it('says which model answered', async () => {
    // Not decoration. Routing chooses per turn, so the model that answered is
    // not necessarily the one the agent is configured with or the one a user
    // picked — and two answers from different models are otherwise identical
    // on screen.
    renderWithProviders(<ChatPage />);

    await send('hello');

    expect(await screen.findByText(/Answered by/)).toBeInTheDocument();
    expect(screen.getByText('mock-echo')).toBeInTheDocument();
  });

  it('continues the conversation the server named', async () => {
    renderWithProviders(<ChatPage />);

    await send('first');
    await screen.findByText('Hello world');
    await send('second');

    await waitFor(() => {
      expect(chatCalls()).toHaveLength(2);
    });
    expect(requestBody(chatCalls()[1] as Parameters<typeof requestBody>[0])).toMatchObject({
      conversation_id: 'c1',
    });
  });
});

describe('Markdown rendering', () => {
  it('renders Markdown structure as elements', async () => {
    routeFetch(() =>
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
    routeFetch(() =>
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
    routeFetch(() =>
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

    routeFetch(() => new Response(null, { status: 204 }));
    await userEvent.setup().click(screen.getByRole('button', { name: 'Clear' }));

    expect(screen.getByText('Start a conversation')).toBeInTheDocument();
    const lastCall = chatCalls().at(-1) as Parameters<typeof requestMethod>[0];
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
      expect(requestUrl(chatCalls().at(-1) as Parameters<typeof requestUrl>[0])).toContain(
        '/conversations/c1/regenerate',
      );
    });
  });
});

describe('Error handling', () => {
  it('shows the backend message when a turn is rejected', async () => {
    routeFetch(
      () =>
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
    routeFetch(() =>
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
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    renderWithProviders(<ChatPage />);

    await send('hello');

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach/i);
  });
});

describe('Tool visibility', () => {
  /**
   * A searching turn spends a whole model call plus the search before the first
   * character arrives. Without this the user watches a blank bubble, which
   * looks exactly like a hang — and afterwards, a searched answer looks
   * identical to an invented one.
   */
  const SEARCH_EVENTS = [
    [
      'started',
      { type: 'started', conversation_id: 'c1', message_id: 'm1', model_id: 'mock-echo' },
    ],
    ['tool', { type: 'tool', tool_id: 'internet-search', summary: 'eiffel tower' }],
    ['delta', { type: 'delta', delta: 'It is ' }],
    ['delta', { type: 'delta', delta: 'a tower.' }],
    [
      'completed',
      {
        type: 'completed',
        message_id: 'm1',
        content: 'It is a tower.',
        usage: { prompt_tokens: 3, completion_tokens: 2 },
        finish_reason: 'stop',
      },
    ],
  ] as const;

  it('shows which tool the agent used, and what it asked', async () => {
    routeFetch(() => streamResponse(sseBody(SEARCH_EVENTS)));
    renderWithProviders(<ChatPage />);

    await send('search for the eiffel tower');

    expect(await screen.findByText(/searched the web/i)).toBeInTheDocument();
    expect(screen.getByText('eiffel tower')).toBeInTheDocument();
  });

  it('keeps the trace visible after the answer arrives', async () => {
    routeFetch(() => streamResponse(sseBody(SEARCH_EVENTS)));
    renderWithProviders(<ChatPage />);

    await send('search for the eiffel tower');

    expect(await screen.findByText('It is a tower.')).toBeInTheDocument();
    expect(screen.getByText(/searched the web/i)).toBeInTheDocument();
  });

  it('does not add the tool summary to the answer text', async () => {
    routeFetch(() => streamResponse(sseBody(SEARCH_EVENTS)));
    renderWithProviders(<ChatPage />);

    await send('search for the eiffel tower');

    const answer = await screen.findByText('It is a tower.');
    expect(answer.textContent).not.toContain('eiffel tower');
  });

  it('shows no trace for a turn that used no tools', async () => {
    routeFetch(() => streamResponse(sseBody(ANSWER_EVENTS)));
    renderWithProviders(<ChatPage />);

    await send('hello');

    await screen.findByText('Hello world');
    expect(screen.queryByText(/searched the web/i)).not.toBeInTheDocument();
  });
});
