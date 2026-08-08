/**
 * ESLint flat configuration.
 *
 * Type-aware linting is enabled deliberately. It is slower than syntactic
 * linting, but it is the only way to catch the mistakes that actually reach
 * production in an async codebase — floating promises, unsafe `any` flowing
 * through a call chain, mishandled unions.
 */

import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';

export default tseslint.config(
  {
    ignores: ['dist/**', 'coverage/**', 'node_modules/**'],
  },

  js.configs.recommended,

  {
    files: ['**/*.{ts,tsx}'],
    // Scoped to TypeScript only. Applied globally, the type-aware rules would
    // also target this config file and the other plain-JS tooling files, which
    // are not part of any tsconfig project and therefore have no type
    // information for those rules to read.
    extends: [...tseslint.configs.strictTypeChecked, ...tseslint.configs.stylisticTypeChecked],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // An unhandled rejection is silent in the browser and impossible to
      // diagnose after the fact.
      '@typescript-eslint/no-floating-promises': 'error',

      // Unused parameters prefixed with `_` are intentional (handler signatures,
      // destructuring rest patterns).
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],

      // `console` in shipped code is the frontend equivalent of `print()`.
      // Warnings and errors stay available for genuine diagnostics.
      'no-console': ['error', { allow: ['warn', 'error'] }],

      // Nullish coalescing over `||` avoids the classic bug where `0` or `''`
      // is treated as absent.
      '@typescript-eslint/prefer-nullish-coalescing': 'error',

      // Numbers stringify unambiguously, so interpolating an HTTP status or a
      // duration into a message needs no ceremony. Objects and nullables stay
      // banned, since those are the cases that produce "[object Object]" and
      // "undefined" in user-facing text.
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
    },
  },

  {
    // Tests assert on values the type system cannot always see, and deliberately
    // construct malformed input.
    files: ['**/*.test.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },

  {
    // Build tooling runs in Node, not the browser.
    files: ['**/*.js', '*.config.ts'],
    languageOptions: {
      globals: globals.node,
    },
  },

  // Must remain last: disables every stylistic rule Prettier already owns.
  prettier,
);
