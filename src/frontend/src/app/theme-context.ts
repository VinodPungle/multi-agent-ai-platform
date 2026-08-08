/**
 * Theme state, separated from the components that render it.
 *
 * Split out so `theme.tsx` exports components only: React Fast Refresh cannot
 * hot-reload a module that mixes components with other exports, and loses
 * component state on every edit when it tries.
 *
 * Three states, not two. "System" is genuinely distinct from light and dark: a
 * user who has not chosen should follow their OS, including when it switches at
 * sunset. Collapsing that into a boolean loses the ability to return to
 * following the system once a choice has been made.
 */

import { createContext, useContext } from 'react';

export type ThemePreference = 'light' | 'dark' | 'system';

export const THEME_STORAGE_KEY = 'agent-platform.theme';

export interface ThemeContextValue {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider.');
  }
  return context;
}

/**
 * Read the stored preference.
 *
 * `localStorage` throws in a sandboxed iframe and when a browser blocks
 * storage. Falling back to `system` is right — an unreadable preference is the
 * same as no preference.
 */
export function readStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system';
  } catch {
    return 'system';
  }
}

export function storePreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Not persisted. The session still honours it.
  }
}

/**
 * Apply the preference to the document.
 *
 * Writing `data-theme` on `<html>` is all it takes: the CSS keys on that
 * attribute, so nothing re-renders to change colour.
 */
export function applyPreference(preference: ThemePreference): void {
  const root = document.documentElement;

  if (preference === 'system') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', preference);
  }

  // Keeps user-agent chrome — scrollbars, form controls, the mobile address bar
  // — in step with the page. Without it a dark page keeps light scrollbars.
  root.style.colorScheme = preference === 'system' ? 'light dark' : preference;
}
