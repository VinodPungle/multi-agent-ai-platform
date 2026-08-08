"""Prompt loading and rendering.

Responsibility
    ``PromptProvider`` implementations that read the versioned assets in the
    repository-root ``prompts/`` directory and resolve them by id and version.

Design rule
    Prompt *text* is never stored here. This package holds the machinery; the
    assets are configuration and live outside the source tree so they can be
    changed, versioned and eventually A/B tested without a code deployment.

Filled in from Milestone 03.
"""
