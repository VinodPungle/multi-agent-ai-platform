/**
 * The chat page.
 *
 * Composes the transcript, the composer and the turn actions. All behaviour
 * comes from `useChat`; this file decides only what is on screen and when.
 */

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { platformQueryKeys } from '@/api/platform';
import { ChatComposer } from '@/features/chat/ChatComposer';
import { ChatHistory } from '@/features/chat/ChatHistory';
import { ChatSettings } from '@/features/chat/ChatSettings';
import { ChatMessage } from '@/features/chat/ChatMessage';
import { useChat, type GenerationOptions } from '@/features/chat/useChat';
import { cn } from '@/utils/cn';

export function ChatPage() {
  const { messages, conversationId, isStreaming, error, send, stop, regenerate, clear, open } =
    useChat();
  const [options, setOptions] = useState<GenerationOptions>({});
  const queryClient = useQueryClient();

  /**
   * Send, then refresh the history list.
   *
   * A new conversation only exists once its first turn has been stored, so the
   * list has to be invalidated after the send rather than before — otherwise
   * the conversation you are looking at is missing from the sidebar beside it.
   */
  async function sendAndRefreshHistory(text: string) {
    await send(text, options);
    await queryClient.invalidateQueries({ queryKey: platformQueryKeys.conversations() });
  }

  const transcriptRef = useRef<HTMLDivElement>(null);
  const isPinnedToBottom = useRef(true);

  // Follow the stream only while the user is already at the bottom. Scrolling
  // them back down after they deliberately scrolled up to re-read something is
  // the single most irritating behaviour a chat UI can have.
  const handleScroll = () => {
    const element = transcriptRef.current;
    if (!element) {
      return;
    }
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    isPinnedToBottom.current = distanceFromBottom < 80;
  };

  useEffect(() => {
    if (!isPinnedToBottom.current) {
      return;
    }
    const element = transcriptRef.current;
    element?.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const hasMessages = messages.length > 0;
  const canRegenerate = Boolean(conversationId) && hasMessages && !isStreaming;

  return (
    <div className="flex h-[calc(100dvh-8rem)] flex-col gap-6 lg:flex-row">
      <ChatHistory
        currentConversationId={conversationId}
        onOpen={(id) => void open(id)}
        disabled={isStreaming}
      />

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
            <p className="text-sm text-muted-foreground">
              Answers come from the model this deployment is configured to use.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void regenerate()}
              disabled={!canRegenerate}
              className={cn(
                'rounded-lg border border-border px-3 py-1.5 text-sm',
                'hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
                'disabled:cursor-not-allowed disabled:opacity-40',
              )}
            >
              Regenerate
            </button>
            <button
              type="button"
              onClick={() => void clear()}
              disabled={!hasMessages}
              className={cn(
                'rounded-lg border border-border px-3 py-1.5 text-sm',
                'hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
                'disabled:cursor-not-allowed disabled:opacity-40',
              )}
            >
              Clear
            </button>
          </div>
        </header>

        <div
          ref={transcriptRef}
          onScroll={handleScroll}
          // `log` + `polite`: a screen reader announces new messages as they
          // arrive without interrupting whatever the user is currently reading.
          role="log"
          aria-live="polite"
          aria-label="Conversation"
          className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-border bg-background p-4"
        >
          {hasMessages ? (
            messages.map((message) => <ChatMessage key={message.id} message={message} />)
          ) : (
            <EmptyState />
          )}
        </div>

        {error && (
          <p
            role="alert"
            className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        <ChatSettings value={options} onChange={setOptions} disabled={isStreaming} />

        <ChatComposer
          onSend={(text) => void sendAndRefreshHistory(text)}
          onStop={stop}
          isStreaming={isStreaming}
        />

        <p className="text-center text-xs text-muted-foreground">
          Conversations are held in server memory for this session and are lost when the backend
          restarts.
        </p>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <p className="text-sm font-medium">Start a conversation</p>
      <p className="max-w-md text-sm text-muted-foreground">
        Ask anything. Responses stream a word at a time and render Markdown, including code blocks
        with syntax highlighting.
      </p>
    </div>
  );
}
