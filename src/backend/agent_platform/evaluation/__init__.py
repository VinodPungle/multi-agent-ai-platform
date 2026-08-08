"""Evaluation and cost tracking.

Responsibility
    ``EvaluationProvider`` implementations that capture latency,
    time-to-first-token, token usage, estimated cost, retries and failures for
    every model invocation (``architecture.md`` §40).

Design rule
    Recording must never fail a request. Losing a telemetry record is always
    preferable to failing the user's call.

Filled in from Milestone 05, with the structured-log implementation first.
"""
