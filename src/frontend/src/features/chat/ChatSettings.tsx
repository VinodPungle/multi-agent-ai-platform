/**
 * Per-turn generation controls: model, temperature and output cap.
 *
 * Collapsed by default. Most turns want the agent's configured behaviour, and a
 * row of sliders above the message box invites fiddling with settings whose
 * effect is hard to see — so the panel is available rather than present.
 *
 * Every control has an explicit "agent default" position rather than starting
 * at some number. That distinction is real, not cosmetic: unset means *the
 * agent decides*, and a temperature of 0 is a deliberate request for
 * determinism. Defaulting the slider to a value would silently override the
 * agent on every turn while looking like it had done nothing.
 */

import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { useModels } from '@/features/catalogue/useCatalogue';
import type { GenerationOptions } from '@/features/chat/useChat';

export interface ChatSettingsProps {
  value: GenerationOptions;
  onChange: (next: GenerationOptions) => void;
  disabled?: boolean;
}

const AGENT_DEFAULT = '';

export function ChatSettings({ value, onChange, disabled = false }: ChatSettingsProps) {
  const [open, setOpen] = useState(false);
  const { data: models } = useModels();

  const overrides = [
    value.modelId,
    value.temperature !== undefined ? 'temperature' : undefined,
    value.maxOutputTokens !== undefined ? 'tokens' : undefined,
  ].filter(Boolean).length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            setOpen((current) => !current);
          }}
          aria-expanded={open}
          className="text-xs font-medium text-muted-foreground underline-offset-4 hover:underline"
        >
          {open ? 'Hide settings' : 'Settings'}
        </button>
        {/* Shown whether or not the panel is open: an override left in place is
            exactly the thing someone forgets, and then wonders why answers
            changed. */}
        {overrides > 0 ? (
          <Badge variant="warning">
            {overrides} override{overrides === 1 ? '' : 's'}
          </Badge>
        ) : null}
        {overrides > 0 ? (
          <button
            type="button"
            onClick={() => {
              onChange({});
            }}
            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            Reset
          </button>
        ) : null}
      </div>

      {open ? (
        <div className="grid gap-4 rounded-lg border border-border bg-card p-4 sm:grid-cols-3">
          <label className="flex flex-col gap-1.5 text-xs">
            <span className="font-medium uppercase tracking-wide text-muted-foreground">Model</span>
            <select
              value={value.modelId ?? AGENT_DEFAULT}
              disabled={disabled}
              onChange={(event) => {
                onChange({ ...value, modelId: event.target.value || undefined });
              }}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            >
              <option value={AGENT_DEFAULT}>Agent default (routing chooses)</option>
              {(models ?? [])
                .filter((model) => model.is_available)
                .map((model) => (
                  <option key={model.model_id} value={model.model_id}>
                    {model.model_id}
                  </option>
                ))}
            </select>
            <span className="text-muted-foreground">
              A model that cannot serve the turn is refused, not swapped.
            </span>
          </label>

          <label className="flex flex-col gap-1.5 text-xs">
            <span className="font-medium uppercase tracking-wide text-muted-foreground">
              Temperature
            </span>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                disabled={disabled}
                value={value.temperature ?? 0.2}
                onChange={(event) => {
                  onChange({ ...value, temperature: Number(event.target.value) });
                }}
                className="w-full"
                aria-label="Temperature"
              />
              <span className="w-8 tabular-nums">
                {value.temperature !== undefined ? value.temperature.toFixed(1) : '—'}
              </span>
            </div>
            <span className="text-muted-foreground">
              {value.temperature === undefined
                ? 'Using the agent’s own setting.'
                : 'Lower is more repeatable; higher is more varied.'}
            </span>
          </label>

          <label className="flex flex-col gap-1.5 text-xs">
            <span className="font-medium uppercase tracking-wide text-muted-foreground">
              Max output tokens
            </span>
            <input
              type="number"
              min={1}
              max={32000}
              step={64}
              disabled={disabled}
              placeholder="Agent default"
              value={value.maxOutputTokens ?? ''}
              onChange={(event) => {
                onChange({
                  ...value,
                  maxOutputTokens: event.target.value ? Number(event.target.value) : undefined,
                });
              }}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            />
            <span className="text-muted-foreground">
              A ceiling, not a target. Budget policy still applies on top.
            </span>
          </label>
        </div>
      ) : null}
    </div>
  );
}
