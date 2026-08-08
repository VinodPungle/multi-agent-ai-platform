/**
 * Markdown renderer for assistant messages.
 *
 * Security first, because this renders text produced by a model, and a model
 * repeats what it was shown. `react-markdown` does not evaluate raw HTML unless
 * `rehype-raw` is added — it is deliberately absent, so `<script>` in a response
 * is displayed as text rather than executed. Nothing here should ever be
 * replaced with `dangerouslySetInnerHTML`.
 *
 * Highlighting runs through `rehype-highlight`, which annotates code with
 * classes at render time. The theme is plain CSS in `globals.css` keyed on those
 * classes, so light and dark follow the same tokens as the rest of the UI
 * instead of shipping two JavaScript themes.
 */

import { memo } from 'react';
import Markdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';

import { CodeBlock } from '@/features/chat/CodeBlock';
import { cn } from '@/utils/cn';

interface MarkdownMessageProps {
  content: string;
  className?: string;
}

/**
 * `memo` matters here rather than being a habit: during a stream this component
 * re-renders on every delta, and re-parsing Markdown dozens of times a second
 * for messages that have not changed is the difference between a smooth stream
 * and a janky one.
 */
export const MarkdownMessage = memo(function MarkdownMessage({
  content,
  className,
}: MarkdownMessageProps) {
  return (
    <div className={cn('flex flex-col gap-3 text-sm leading-relaxed', className)}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[
          [
            rehypeHighlight,
            {
              // `ignoreMissing`: a fenced block tagged with a language lowlight
              // does not know renders as plain code instead of throwing. A model
              // can emit any tag, and one unusual answer must not break the
              // whole message.
              ignoreMissing: true,
              // Detection off. On a short snippet it guesses wrong often enough
              // to be worse than no colour at all, and a mislabelled language is
              // more confusing than an unstyled block.
              detect: false,
            },
          ],
        ]}
        components={{
          // Tailwind's preflight removes default element styling, so every
          // element a model can emit needs an explicit rule. Anything missed
          // renders as unstyled text, which looks like a bug in the answer.
          p: ({ children }) => <p className="whitespace-pre-wrap break-words">{children}</p>,
          h1: ({ children }) => <h1 className="text-lg font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="text-base font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold">{children}</h3>,
          ul: ({ children }) => (
            <ul className="list-disc space-y-1 pl-5 marker:text-muted-foreground">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal space-y-1 pl-5 marker:text-muted-foreground">{children}</ol>
          ),
          li: ({ children }) => <li className="break-words">{children}</li>,
          a: ({ children, href }) => (
            <a
              href={href}
              // A model can emit any URL. `noopener` denies the target page
              // access to `window.opener`; `noreferrer` withholds the referrer.
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-primary underline underline-offset-2 hover:no-underline"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-border pl-3 text-muted-foreground">
              {children}
            </blockquote>
          ),
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          hr: () => <hr className="border-border" />,
          table: ({ children }) => (
            // Wide tables scroll inside the bubble rather than widening the page.
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border px-2 py-1 font-semibold">{children}</th>
          ),
          td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
          code: CodeBlock,
        }}
      >
        {content}
      </Markdown>
    </div>
  );
});
