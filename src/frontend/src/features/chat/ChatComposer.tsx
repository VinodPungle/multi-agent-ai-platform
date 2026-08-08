/**
 * The message input.
 *
 * Enter sends, Shift+Enter inserts a newline — the convention every chat product
 * shares, and the one users try first. A plain textarea that only submits on a
 * button click feels broken.
 *
 * The textarea grows with its content up to a cap, then scrolls. Without the cap
 * a long paste pushes the transcript off screen entirely.
 */

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';

import { cn } from '@/utils/cn';

const MAX_HEIGHT_PX = 200;

interface ChatComposerProps {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export function ChatComposer({ onSend, onStop, isStreaming, disabled }: ChatComposerProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Height is reset before being measured, or the box can only ever grow:
  // `scrollHeight` of an already-tall element never reports a smaller value.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_HEIGHT_PX).toString()}px`;
  }, [value]);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming || disabled) {
      return;
    }
    onSend(trimmed);
    setValue('');
  }, [disabled, isStreaming, onSend, value]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      // `isComposing` guards an IME: pressing Enter to accept a candidate in
      // Japanese, Chinese or Korean input must not send a half-typed message.
      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
        event.preventDefault();
        submit();
      }
    },
    [submit],
  );

  const canSend = value.trim().length > 0 && !isStreaming && !disabled;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2 focus-within:border-primary"
    >
      <label htmlFor="chat-input" className="sr-only">
        Message
      </label>
      <textarea
        id="chat-input"
        ref={textareaRef}
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
        }}
        onKeyDown={handleKeyDown}
        rows={1}
        disabled={disabled}
        placeholder="Send a message…  (Enter to send, Shift+Enter for a new line)"
        className={cn(
          'flex-1 resize-none bg-transparent px-2 py-2 text-sm text-foreground',
          'placeholder:text-muted-foreground focus:outline-none disabled:opacity-50',
        )}
      />

      {isStreaming ? (
        <button
          type="button"
          onClick={onStop}
          className={cn(
            'shrink-0 rounded-xl border border-border px-4 py-2 text-sm font-medium',
            'hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
          )}
        >
          Stop
        </button>
      ) : (
        <button
          type="submit"
          disabled={!canSend}
          className={cn(
            'shrink-0 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground',
            'hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
            'disabled:cursor-not-allowed disabled:opacity-40',
          )}
        >
          Send
        </button>
      )}
    </form>
  );
}
