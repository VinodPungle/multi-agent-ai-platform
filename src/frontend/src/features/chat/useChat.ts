/**
 * Chat state and the streaming lifecycle.
 *
 * All of the feature's behaviour lives here so the components stay presentational
 * and testable without a DOM: send, stop, regenerate, clear, and the error
 * handling around each.
 *
 * Not TanStack Query, deliberately. Query is built around cacheable
 * request/response resources; a chat turn is a long-lived stream that mutates a
 * local buffer dozens of times per second and must be cancellable mid-flight.
 * Modelling that as a query would mean fighting the cache on every delta. Query
 * still owns the *conversation history* fetch, which is a genuine cached
 * resource.
 */

import { useCallback, useRef, useState } from 'react';

import { ApiError } from '@/api/client';
import { clearConversation } from '@/api/platform';
import { regenerateChat, streamChat, type ChatStreamEvent } from '@/api/chat';

export type MessageStatus = 'complete' | 'streaming' | 'stopped' | 'failed';

export interface ChatMessageView {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  status: MessageStatus;
  /** Present when the turn failed, for display beside the message. */
  error?: string;
}

export interface ChatState {
  messages: readonly ChatMessageView[];
  conversationId: string | null;
  /** True from submission until the stream ends, however it ends. */
  isStreaming: boolean;
  /** A failure that has no message to attach itself to. */
  error: string | null;
}

/** A locally-generated id for a message the server has not named yet. */
function localId(prefix: string): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useChat() {
  const [messages, setMessages] = useState<readonly ChatMessageView[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A ref, not state: aborting must not depend on a re-render having happened,
  // and the controller is never rendered.
  const abortRef = useRef<AbortController | null>(null);

  const appendDelta = useCallback((assistantId: string, delta: string) => {
    setMessages((current) =>
      current.map((message) =>
        message.id === assistantId ? { ...message, content: message.content + delta } : message,
      ),
    );
  }, []);

  const finalise = useCallback((assistantId: string, patch: Partial<ChatMessageView>) => {
    setMessages((current) =>
      current.map((message) => (message.id === assistantId ? { ...message, ...patch } : message)),
    );
  }, []);

  /**
   * Consume a stream, applying each event to local state.
   *
   * Shared by send and regenerate: the two differ only in which request opens
   * the stream, and duplicating the consumption loop would mean fixing every
   * streaming bug twice.
   */
  const consume = useCallback(
    async (events: AsyncGenerator<ChatStreamEvent, void>, assistantId: string) => {
      let receivedAnything = false;

      try {
        for await (const event of events) {
          switch (event.type) {
            case 'started':
              setConversationId(event.conversation_id);
              break;
            case 'delta':
              receivedAnything = true;
              appendDelta(assistantId, event.delta);
              break;
            case 'completed':
              // The terminal event carries the full text. Adopting it rather
              // than trusting the accumulated deltas means a dropped frame
              // self-corrects instead of leaving a silently truncated answer.
              finalise(assistantId, { content: event.content, status: 'complete' });
              break;
            case 'error':
              finalise(assistantId, { status: 'failed', error: event.message });
              break;
          }
        }
      } catch (caught) {
        const message =
          caught instanceof ApiError
            ? caught.message
            : 'Something went wrong while generating the response.';

        if (receivedAnything) {
          finalise(assistantId, { status: 'failed', error: message });
        } else {
          // Nothing was rendered, so there is no message to attach the failure
          // to. Remove the empty placeholder rather than leaving a blank bubble.
          setMessages((current) => current.filter((entry) => entry.id !== assistantId));
          setError(message);
        }
      } finally {
        // A stream still marked `streaming` here was stopped by the user: the
        // loop exited without a terminal event.
        setMessages((current) =>
          current.map((entry) =>
            entry.id === assistantId && entry.status === 'streaming'
              ? { ...entry, status: 'stopped' }
              : entry,
          ),
        );
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [appendDelta, finalise],
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) {
        return;
      }

      setError(null);
      const assistantId = localId('assistant');

      setMessages((current) => [
        ...current,
        { id: localId('user'), role: 'user', content: trimmed, status: 'complete' },
        { id: assistantId, role: 'assistant', content: '', status: 'streaming' },
      ]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      await consume(
        streamChat({
          message: trimmed,
          conversationId: conversationId ?? undefined,
          signal: controller.signal,
        }),
        assistantId,
      );
    },
    [consume, conversationId, isStreaming],
  );

  const regenerate = useCallback(async () => {
    if (!conversationId || isStreaming) {
      return;
    }

    setError(null);
    const assistantId = localId('assistant');

    // Drop the previous answer from the view as the server drops it from
    // history, so the two never disagree about what the conversation contains.
    setMessages((current) => {
      const withoutLastAnswer = [...current];
      while (
        withoutLastAnswer.length > 0 &&
        withoutLastAnswer[withoutLastAnswer.length - 1]?.role === 'assistant'
      ) {
        withoutLastAnswer.pop();
      }
      return [
        ...withoutLastAnswer,
        { id: assistantId, role: 'assistant', content: '', status: 'streaming' },
      ];
    });
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    await consume(regenerateChat(conversationId, controller.signal), assistantId);
  }, [consume, conversationId, isStreaming]);

  /**
   * Stop the current generation.
   *
   * Aborting the request closes the connection, which the backend sees as a
   * disconnect: it stops generating and keeps the partial answer in history. The
   * text already on screen therefore matches what the server stored.
   */
  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  /** Forget the conversation, on the server and locally. */
  const clear = useCallback(async () => {
    abortRef.current?.abort();
    abortRef.current = null;

    const existing = conversationId;

    setMessages([]);
    setConversationId(null);
    setIsStreaming(false);
    setError(null);

    if (existing) {
      try {
        await clearConversation(existing);
      } catch {
        // The local view is already empty and a new conversation id will be
        // issued on the next turn, so a failed delete leaves nothing visibly
        // wrong. Surfacing it would be noise about a resource the user has
        // already moved on from; it is bounded and evicted server-side.
      }
    }
  }, [conversationId]);

  const state: ChatState = { messages, conversationId, isStreaming, error };

  return { ...state, send, stop, regenerate, clear };
}
