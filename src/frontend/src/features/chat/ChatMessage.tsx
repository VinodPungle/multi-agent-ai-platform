/**
 * One message in the transcript.
 *
 * User and assistant messages are deliberately asymmetric. User text is
 * rendered literally — it is not Markdown, and treating it as such would mangle
 * an underscore in a variable name and, worse, interpret whatever a user pasted.
 * Assistant text is Markdown, because that is what the model was asked to
 * produce.
 */

import { MarkdownMessage } from '@/features/chat/MarkdownMessage';
import type { ChatMessageView } from '@/features/chat/useChat';
import { cn } from '@/utils/cn';

interface ChatMessageProps {
  message: ChatMessageView;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

  return (
    <article
      // `group`/`article` rather than a bare div: assistive technology can then
      // navigate the transcript message by message.
      aria-label={isUser ? 'Your message' : 'Assistant message'}
      className={cn('flex w-full gap-3', isUser ? 'justify-end' : 'justify-start')}
    >
      {!isUser && (
        <div
          aria-hidden="true"
          className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
        >
          AI
        </div>
      )}

      <div
        className={cn(
          'max-w-[min(46rem,85%)] rounded-2xl px-4 py-3',
          isUser
            ? 'bg-primary text-primary-foreground'
            : 'border border-border bg-card text-card-foreground',
        )}
      >
        {isUser ? (
          // `whitespace-pre-wrap` keeps the line breaks the user typed;
          // `break-words` stops an unbroken URL widening the whole layout.
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            {message.content}
          </p>
        ) : (
          <>
            {message.content ? (
              <MarkdownMessage content={message.content} />
            ) : (
              message.status === 'streaming' && <TypingIndicator />
            )}

            {message.status === 'streaming' && message.content && (
              <span
                aria-hidden="true"
                className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground align-middle"
              />
            )}

            {message.status === 'stopped' && (
              <p className="mt-2 text-xs text-muted-foreground">Stopped by you.</p>
            )}

            {message.status === 'failed' && message.error && (
              <p role="alert" className="mt-2 text-xs text-danger">
                {message.error}
              </p>
            )}
          </>
        )}
      </div>
    </article>
  );
}

/**
 * Shown between submitting and the first token arriving.
 *
 * Announced politely rather than silently animated: without the live region a
 * screen reader user gets no feedback at all between pressing send and the
 * answer appearing.
 */
export function TypingIndicator() {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-1 py-1">
      <span className="sr-only">Generating a response</span>
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          aria-hidden="true"
          className="size-1.5 animate-bounce rounded-full bg-muted-foreground"
          style={{ animationDelay: `${index * 150}ms` }}
        />
      ))}
    </div>
  );
}
