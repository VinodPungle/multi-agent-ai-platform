/**
 * Code rendering for Markdown content.
 *
 * `react-markdown` uses one `code` component for both inline spans and fenced
 * blocks, so this decides which it is. The signal is the language class
 * `rehype-highlight` attaches (`language-python`) — present on a fenced block
 * with a language tag, absent on inline code.
 *
 * The copy button is here rather than in the message: a message can contain
 * several blocks, and copying "the code" from a response with three snippets is
 * ambiguous. Per block it never is.
 */

import { useCallback, useState, type ComponentPropsWithoutRef, type ReactNode } from 'react';

import { cn } from '@/utils/cn';

type CodeProps = ComponentPropsWithoutRef<'code'> & { children?: ReactNode };

/** Extract the language from the class `rehype-highlight` applies. */
function languageOf(className: string | undefined): string | null {
  const match = /language-([\w+-]+)/.exec(className ?? '');
  return match?.[1] ?? null;
}

function textOf(children: ReactNode): string {
  if (typeof children === 'string') {
    return children;
  }
  if (Array.isArray(children)) {
    return children.map(textOf).join('');
  }
  return '';
}

export function CodeBlock({ className, children, ...props }: CodeProps) {
  const language = languageOf(className);
  const isBlock = language !== null || textOf(children).includes('\n');

  if (!isBlock) {
    return (
      <code
        className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground"
        {...props}
      >
        {children}
      </code>
    );
  }

  return (
    <figure className="group relative overflow-hidden rounded-lg border border-border bg-muted">
      <figcaption className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <span className="font-mono text-xs text-muted-foreground">{language ?? 'text'}</span>
        <CopyButton value={textOf(children)} />
      </figcaption>
      <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
        <code className={cn('font-mono', className)} {...props}>
          {children}
        </code>
      </pre>
    </figure>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    void (async () => {
      try {
        // `navigator.clipboard` is typed as always present but is genuinely
        // absent on insecure origins, which includes some LAN development
        // setups. `try` covers both that (a synchronous TypeError) and a denied
        // permission (a rejection) — a truthiness guard would only cover one,
        // and the types insist it is unnecessary anyway.
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, 2000);
      } catch {
        // Failing silently is right: the code is on screen and selectable, so
        // an error toast would be noise about a non-problem.
      }
    })();
  }, [value]);

  return (
    <button
      type="button"
      onClick={copy}
      // `aria-live` announces the change to a screen reader; a purely visual
      // "Copied" tells a screen reader user nothing.
      aria-live="polite"
      className={cn(
        'rounded px-2 py-0.5 text-xs text-muted-foreground transition-colors',
        'hover:bg-background hover:text-foreground',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
      )}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}
