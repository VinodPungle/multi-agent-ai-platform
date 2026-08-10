/**
 * Past conversations.
 *
 * Summaries rather than transcripts: the list shows how each conversation
 * started and how long it got, and opening one fetches its messages. Showing
 * twenty conversations should not mean transferring twenty full histories.
 *
 * The preview is the *first* user message rather than the most recent, because
 * a history list is scanned to find something again and people remember how a
 * conversation started.
 */

import { useQuery } from '@tanstack/react-query';

import { ApiError } from '@/api/client';
import { fetchConversations, platformQueryKeys } from '@/api/platform';
import { cn } from '@/utils/cn';

export interface ChatHistoryProps {
  currentConversationId: string | null;
  onOpen: (conversationId: string) => void;
  disabled?: boolean;
}

export function ChatHistory({ currentConversationId, onOpen, disabled = false }: ChatHistoryProps) {
  const { data, error, isPending, isError } = useQuery<unknown[], ApiError>({
    queryKey: platformQueryKeys.conversations(),
    queryFn: ({ signal }) => fetchConversations(50, { signal }),
    // Refetched when the window regains focus rather than polled: the list
    // changes when *this* user sends a message, and they were here when it
    // happened.
    staleTime: 0,
  });

  const conversations = (data ?? []) as {
    conversation_id: string;
    message_count: number;
    preview: string;
  }[];

  return (
    <aside className="flex w-full flex-col gap-3 lg:w-72">
      <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">History</h2>

      {isPending ? (
        <p className="text-sm text-muted-foreground" aria-live="polite">
          Loading…
        </p>
      ) : isError ? (
        // Deliberately not `role="alert"`. History being unavailable degrades a
        // sidebar; the chat error beside it is the one worth interrupting a
        // screen reader for, and two competing alerts serve neither.
        <p className="text-sm text-muted-foreground">
          History is unavailable — chat still works. ({error.message})
        </p>
      ) : conversations.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No past conversations. They appear here as you chat, and are held in server memory — a
          backend restart clears them unless durable memory is configured.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {conversations.map((conversation) => {
            const isCurrent = conversation.conversation_id === currentConversationId;
            return (
              <li key={conversation.conversation_id}>
                <button
                  type="button"
                  disabled={disabled}
                  aria-current={isCurrent ? 'true' : undefined}
                  onClick={() => {
                    onOpen(conversation.conversation_id);
                  }}
                  className={cn(
                    'w-full rounded-md border px-3 py-2 text-left transition-colors',
                    'disabled:cursor-not-allowed disabled:opacity-50',
                    isCurrent
                      ? 'border-primary/40 bg-primary/5'
                      : 'border-border hover:bg-muted/50',
                  )}
                >
                  <span className="line-clamp-2 block text-sm">
                    {conversation.preview || 'Untitled conversation'}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {conversation.message_count} message
                    {conversation.message_count === 1 ? '' : 's'}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
