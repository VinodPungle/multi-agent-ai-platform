/**
 * Theme provider and toggle.
 *
 * Components only — the context, hook and DOM helpers live in `theme-context.ts`
 * so Fast Refresh can hot-reload this file without losing state.
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react';

import {
  ThemeContext,
  applyPreference,
  readStoredPreference,
  storePreference,
  useTheme,
  type ThemePreference,
} from '@/app/theme-context';

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);

  useEffect(() => {
    applyPreference(preference);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    storePreference(next);
  }, []);

  return <ThemeContext value={{ preference, setPreference }}>{children}</ThemeContext>;
}

const NEXT_PREFERENCE: Record<ThemePreference, ThemePreference> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
};

const PREFERENCE_LABEL: Record<ThemePreference, string> = {
  system: 'System theme',
  light: 'Light theme',
  dark: 'Dark theme',
};

const PREFERENCE_ICON: Record<ThemePreference, string> = {
  system: '◐',
  light: '☀',
  dark: '☾',
};

/** Cycles system → light → dark → system. */
export function ThemeToggle() {
  const { preference, setPreference } = useTheme();

  return (
    <button
      type="button"
      onClick={() => {
        setPreference(NEXT_PREFERENCE[preference]);
      }}
      // The glyph is decorative; the accessible name states the current theme
      // and is what a screen reader announces.
      aria-label={`${PREFERENCE_LABEL[preference]}. Activate to switch.`}
      title={PREFERENCE_LABEL[preference]}
      className="rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
    >
      <span aria-hidden="true">{PREFERENCE_ICON[preference]}</span>
    </button>
  );
}
