"""Narrow helpers with no better home.

Design rule
    This package is a last resort, kept deliberately small. The handbook bans
    ``Util``/``Helper``/``Manager`` naming precisely because such modules
    accumulate unrelated logic. Anything with a real responsibility belongs in a
    package named after that responsibility.

Cross-cutting mechanics that other services also need belong in
``agent_platform_shared``, not here.
"""
