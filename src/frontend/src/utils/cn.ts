/**
 * Class name composition helper.
 *
 * `clsx` resolves conditional class lists; `tailwind-merge` then removes
 * conflicting Tailwind utilities so that a caller's `px-4` reliably overrides a
 * component's default `px-2`. Without the merge step the later class only wins
 * by accident of CSS source order.
 *
 * This is the standard shadcn/ui utility, kept here so shadcn components can be
 * added without modification.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
