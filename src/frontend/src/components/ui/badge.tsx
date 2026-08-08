/**
 * Status badge.
 *
 * A shadcn/ui-style primitive: variant-driven, composable, and extended rather
 * than replaced. Colours are expressed through the design tokens in
 * `styles/globals.css`, never as literal hex values, so light and dark themes
 * stay consistent.
 */

import type { HTMLAttributes } from 'react';

import { cn } from '@/utils/cn';

export type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'muted';

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-primary/10 text-primary ring-primary/20',
  success: 'bg-success/10 text-success ring-success/20',
  warning: 'bg-warning/10 text-warning ring-warning/20',
  danger: 'bg-danger/10 text-danger ring-danger/20',
  muted: 'bg-muted text-muted-foreground ring-border',
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ variant = 'default', className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5',
        'text-xs font-medium ring-1 ring-inset',
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  );
}
