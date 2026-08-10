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
import type { ChatMessageView, ToolActivity } from '@/features/chat/useChat';
import { cn } from '@/utils/cn';

/** Human-readable names for the tools a user may see. */
const toolLabels: Record<string, string> = {
  'internet-search': 'Searched the web',
};

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
            {message.tools && message.tools.length > 0 && (
              <ToolTrace tools={message.tools} pending={message.status === 'streaming'} />
            )}

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

            {/* Which model actually answered.

                Shown per message rather than once at the top of the page,
                because it can differ between turns: routing chooses per turn,
                and a model pinned for one question is not pinned for the next.
                Two answers from different models would otherwise look
                identical. */}
            {message.modelId && (
              <p className="mt-2 border-t border-border/60 pt-2 text-xs text-muted-foreground">
                Answered by <span className="font-mono">{message.modelId}</span>
              </p>
            )}
          </>
        )}
      </div>
    </article>
  );
}

/**
 * What the agent did before answering.
 *
 * Shown above the answer and kept there afterwards. During the pause it
 * explains several seconds of silence that would otherwise be indistinguishable
 * from a hang; afterwards it is what separates a grounded answer from an
 * invented one, which is worth more than the transient reassurance.
 */
function ToolTrace({ tools, pending }: { tools: readonly ToolActivity[]; pending: boolean }) {
  return (
    <ul
      aria-label="Tools used for this answer"
      className="mb-2 flex flex-col gap-1 border-b border-border pb-2"
    >
      {tools.map((tool, index) => (
        <li
          key={`${tool.toolId}-${index}`}
          className="flex items-center gap-2 text-xs text-muted-foreground"
        >
          <span
            aria-hidden="true"
            className={cn(
              'size-1.5 shrink-0 rounded-full',
              pending ? 'animate-pulse bg-primary' : 'bg-muted-foreground',
            )}
          />
          <span className="truncate">
            {toolLabels[tool.toolId] ?? tool.toolId}
            {tool.summary && (
              <>
                {': '}
                <span className="italic">{tool.summary}</span>
              </>
            )}
          </span>
        </li>
      ))}
    </ul>
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
