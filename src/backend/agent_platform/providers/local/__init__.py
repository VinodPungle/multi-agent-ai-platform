"""Providers that run on the machine the platform runs on.

Responsibility
    Implementations that need no cloud service — currently semantic embeddings
    through a local ONNX model.

Design rule
    Same contracts as every other provider. A local implementation is a
    deployment choice, not a different kind of thing, so nothing above the
    composition root can tell whether embeddings came from here or from Azure.

Added in Milestone 09.
"""
