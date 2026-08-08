"""Generation of the identifiers that make a request traceable end to end.

Identifier generation is centralised so that format changes (for example moving
to ULIDs for lexicographic sortability) happen in one place rather than in every
call site that needs an id.
"""

from __future__ import annotations

import uuid

__all__ = ["new_correlation_id", "new_execution_id", "new_request_id"]


def _new_id() -> str:
    """Return a new opaque identifier.

    UUID4 is used rather than a sequential scheme because identifiers are
    generated independently by every replica and must not collide without
    coordination.
    """
    return str(uuid.uuid4())


def new_correlation_id() -> str:
    """Return an identifier for a logical end-to-end operation.

    A correlation id spans every hop of a single user-visible operation: the
    HTTP request, the runtime execution, agent hand-offs, tool calls and
    provider calls. Callers may supply their own via the correlation header, in
    which case this function is not used.
    """
    return _new_id()


def new_request_id() -> str:
    """Return an identifier for a single inbound HTTP request.

    Distinct from the correlation id: one correlation may span several requests
    (for example a retry from a client, or a streaming reconnect), and each of
    those gets its own request id.
    """
    return _new_id()


def new_execution_id() -> str:
    """Return an identifier for a single agent or workflow execution.

    One request may trigger several executions when the runtime orchestrates
    multiple agents. Used from Milestone 03 onward.
    """
    return _new_id()
