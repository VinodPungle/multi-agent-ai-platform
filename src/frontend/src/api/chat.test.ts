/**
 * SSE parsing and the streaming client.
 *
 * The chunk-boundary tests are the point of this file. A parser that only works
 * when each network chunk happens to contain whole frames passes every naive
 * test and drops events against a real server, where a boundary can fall
 * anywhere — mid-frame, mid-line, mid-UTF-8 sequence.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/api/client';
import { parseSseFrames, streamChat, type ChatStreamEvent } from '@/api/chat';
import { requestBody } from '@/test/fetchAssertions';

/** Build a `ReadableStream` that emits `chunks` as encoded bytes, in order. */
function streamOf(chunks: readonly string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

async function collect<T>(source: AsyncGenerator<T, void>): Promise<T[]> {
  const items: T[] = [];
  for await (const item of source) {
    items.push(item);
  }
  return items;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('parseSseFrames', () => {
  it('parses a single frame', async () => {
    const frames = await collect(parseSseFrames(streamOf(['event: delta\ndata: {"a":1}\n\n'])));

    expect(frames).toEqual([{ event: 'delta', data: '{"a":1}' }]);
  });

  it('parses several frames from one chunk', async () => {
    const frames = await collect(
      parseSseFrames(streamOf(['event: a\ndata: 1\n\nevent: b\ndata: 2\n\n'])),
    );

    expect(frames.map((frame) => frame.event)).toEqual(['a', 'b']);
  });

  it('reassembles a frame split across chunks', async () => {
    const frames = await collect(
      parseSseFrames(streamOf(['event: del', 'ta\ndata: {"va', 'lue":1}\n\n'])),
    );

    expect(frames).toEqual([{ event: 'delta', data: '{"value":1}' }]);
  });

  it('handles a chunk boundary falling exactly on the frame separator', async () => {
    const frames = await collect(parseSseFrames(streamOf(['event: a\ndata: 1\n', '\n'])));

    expect(frames).toHaveLength(1);
  });

  it('keeps a multi-byte character split across chunks intact', async () => {
    // "é" is two bytes in UTF-8. Decoding each chunk independently would
    // produce replacement characters instead.
    const encoder = new TextEncoder();
    const bytes = encoder.encode('event: delta\ndata: {"delta":"é"}\n\n');
    const split = Math.floor(bytes.length / 2);

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, split));
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    });

    const frames = await collect(parseSseFrames(stream));

    expect(frames[0]?.data).toContain('é');
  });

  it('ignores comment frames', async () => {
    const frames = await collect(
      parseSseFrames(streamOf([': stream open\n\nevent: delta\ndata: 1\n\n'])),
    );

    expect(frames).toHaveLength(1);
  });

  it('ignores a trailing partial frame', async () => {
    // A connection dropped mid-frame must not yield a truncated event.
    const frames = await collect(
      parseSseFrames(streamOf(['event: a\ndata: 1\n\nevent: b\ndata:'])),
    );

    expect(frames).toHaveLength(1);
  });

  it('joins multi-line data fields', async () => {
    const frames = await collect(parseSseFrames(streamOf(['event: a\ndata: one\ndata: two\n\n'])));

    expect(frames[0]?.data).toBe('one\ntwo');
  });

  it('stops when the signal is aborted', async () => {
    const controller = new AbortController();
    controller.abort();

    const frames = await collect(
      parseSseFrames(streamOf(['event: a\ndata: 1\n\n']), controller.signal),
    );

    expect(frames).toEqual([]);
  });
});

describe('streamChat', () => {
  function mockStreamResponse(body: string): void {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        }),
      ),
    );
  }

  it('yields parsed events', async () => {
    mockStreamResponse(
      'event: started\ndata: {"type":"started","conversation_id":"c1","message_id":"m1","model_id":"mock-echo","provider_id":"mock"}\n\n' +
        'event: delta\ndata: {"type":"delta","delta":"Hello"}\n\n' +
        'event: completed\ndata: {"type":"completed","message_id":"m1","content":"Hello","usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n',
    );

    const events = await collect(streamChat({ message: 'hi' }));

    expect(events.map((event: ChatStreamEvent) => event.type)).toEqual([
      'started',
      'delta',
      'completed',
    ]);
  });

  it('sends the conversation id when continuing a conversation', async () => {
    mockStreamResponse('event: delta\ndata: {"type":"delta","delta":"x"}\n\n');

    await collect(streamChat({ message: 'hi', conversationId: 'c1' }));

    expect(requestBody(vi.mocked(fetch).mock.calls[0])).toEqual({
      message: 'hi',
      conversation_id: 'c1',
    });
  });

  it('omits the conversation id when starting a new conversation', async () => {
    mockStreamResponse('event: delta\ndata: {"type":"delta","delta":"x"}\n\n');

    await collect(streamChat({ message: 'hi' }));

    expect(requestBody(vi.mocked(fetch).mock.calls[0])).toEqual({ message: 'hi' });
  });

  it('raises the backend error when the request is rejected before the stream opens', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { category: 'validation', message: 'A message cannot be empty.' },
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    await expect(collect(streamChat({ message: ' ' }))).rejects.toThrow(
      'A message cannot be empty.',
    );
  });

  it('reports a transport failure as a network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(collect(streamChat({ message: 'hi' }))).rejects.toBeInstanceOf(ApiError);
  });

  it('treats cancellation before the response as a normal end', async () => {
    // The user pressed stop. Not a failure, and must not surface as one.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')));

    await expect(collect(streamChat({ message: 'hi' }))).resolves.toEqual([]);
  });

  it('rejects an event whose shape does not match the contract', async () => {
    mockStreamResponse('event: delta\ndata: {"type":"delta"}\n\n');

    await expect(collect(streamChat({ message: 'hi' }))).rejects.toThrow(/unexpected format/i);
  });
});
