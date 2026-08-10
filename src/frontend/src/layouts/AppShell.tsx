/**
 * The platform portal shell.
 *
 * The handbook frames the frontend as an *AI Platform Portal* in which chat is
 * one module among many — agents, models, prompts, evaluations, cost, settings,
 * administration, monitoring. The navigation is built from a data array so that
 * adding a module is one entry, not a layout change.
 *
 * Modules not yet delivered are shown disabled rather than hidden: the roadmap
 * stays visible without pretending the routes exist.
 */

import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

import { ThemeToggle } from '@/app/theme';
import { env } from '@/config/env';
import { cn } from '@/utils/cn';

interface NavigationItem {
  label: string;
  /** `undefined` until the module exists. */
  href?: string;
  milestone?: string;
}

const navigation: readonly NavigationItem[] = [
  { label: 'Overview', href: '/' },
  { label: 'Chat', href: '/chat' },
  { label: 'Agents', milestone: 'M03' },
  { label: 'Tools', milestone: 'M04' },
  { label: 'Models', milestone: 'M05' },
  { label: 'Evaluations', milestone: 'future' },
  { label: 'Cost', href: '/cost' },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <a
        // Keyboard users must be able to skip repeated navigation
        // (handbook, "Accessibility").
        href="#main"
        className={cn(
          'sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50',
          'focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground',
        )}
      >
        Skip to content
      </a>

      <header className="border-b border-border">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4">
          <span className="text-sm font-semibold tracking-tight">{env.VITE_APP_NAME}</span>

          <nav aria-label="Platform modules" className="flex-1">
            <ul className="flex flex-wrap items-center gap-1">
              {navigation.map((item) => (
                <li key={item.label}>
                  {item.href ? (
                    <NavLink
                      to={item.href}
                      // `end` on the root route only, or "Overview" stays
                      // highlighted on every page beneath it.
                      end={item.href === '/'}
                      className={({ isActive }) =>
                        cn(
                          'rounded-md px-2.5 py-1.5 text-sm font-medium hover:bg-muted',
                          isActive ? 'bg-muted text-foreground' : 'text-muted-foreground',
                        )
                      }
                    >
                      {item.label}
                    </NavLink>
                  ) : (
                    <span
                      aria-disabled="true"
                      title={`Planned for ${item.milestone ?? 'a future milestone'}`}
                      className="cursor-not-allowed rounded-md px-2.5 py-1.5 text-sm text-muted-foreground"
                    >
                      {item.label}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </nav>

          <ThemeToggle />
        </div>
      </header>

      <main id="main" className="mx-auto max-w-5xl px-4 py-8">
        {children}
      </main>
    </div>
  );
}
