"""Model catalogue.

Responsibility
    Loading and validating ``ModelDescriptor`` definitions — context windows,
    output limits, capabilities and pricing — from configuration.

Design rule
    Model metadata is data, never a Python constant. Adding a model or changing
    a price is a configuration change (``architecture.md`` §30).

Filled in from Milestone 05.
"""
