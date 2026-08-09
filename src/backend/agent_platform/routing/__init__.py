"""Model routing.

Responsibility
    Choosing *which model* answers a turn, and recording why. Selection is a
    chain of small policies over the model registry's catalogue
    (``architecture.md`` §44, ``CLAUDE.md`` "Runtime Model Selection").

Design rule
    Nothing here calls a model, opens a connection or reads a clock. A routing
    decision must be reproducible from its inputs, because the question it has
    to answer months later is "why did this request use that model?".

Added in Milestone 09.
"""
