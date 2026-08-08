"""Server-sent event encoding.

SSE rather than WebSockets for streaming answers. The traffic is one-way and
request-scoped, which is precisely what SSE is for: it rides on plain HTTP, so
it inherits the existing middleware, error handling, correlation headers,
proxies and load balancers rather than needing a parallel path for all of them.
A WebSocket would buy bidirectionality that a request-response turn does not use.

The wire format is four framing rules, and getting any of them wrong produces a
stream that works in development and stalls in production:

``event:``
    Names the event so a browser can attach a listener per type instead of
    parsing every payload to discover what it is.
``data:``
    One line per line of payload. A raw newline inside a ``data:`` line ends the
    field, so multi-line JSON must be split across repeated ``data:`` lines —
    the receiver rejoins them.
``\\n\\n``
    Terminates an event. Without the blank line the client buffers indefinitely
    and nothing is delivered.
``: comment``
    Ignored by clients, and the only way to push bytes without emitting an
    event — which is how idle connections are kept from being reaped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

from pydantic import BaseModel

__all__ = [
    "SSE_HEADERS",
    "SSE_MEDIA_TYPE",
    "format_comment",
    "format_event",
    "sse_stream",
]

SSE_MEDIA_TYPE = "text/event-stream"

#: Response headers every SSE endpoint needs.
#:
#: ``Cache-Control`` and ``Connection`` are the obvious ones. ``X-Accel-Buffering``
#: is the one that is always forgotten: nginx buffers proxied responses by
#: default, so an SSE stream behind it arrives as one block at the end. The
#: symptom — streaming works locally, appears broken once deployed — costs hours
#: to diagnose, and this header is the whole fix.
SSE_HEADERS: Mapping[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_event(event_name: str, payload: BaseModel) -> str:
    """Encode one event as an SSE frame.

    Args:
        event_name: Value of the ``event:`` field.
        payload: Model serialised to JSON as the ``data:`` field.

    Returns:
        A complete frame including its terminating blank line.
    """
    # `mode="json"` so that Decimal and enum values serialise to JSON-native
    # types rather than to Python reprs a browser cannot parse.
    body = payload.model_dump_json()

    # Defensive rather than theoretical: JSON encodes literal newlines inside
    # strings as `\n`, so the body is normally one line — but a future encoder
    # setting, or an indented dump, would silently corrupt every frame.
    data_lines = "\n".join(f"data: {line}" for line in body.split("\n"))

    return f"event: {event_name}\n{data_lines}\n\n"


def format_comment(text: str) -> str:
    """Encode a comment frame.

    Delivers bytes without delivering an event. Used to keep an idle connection
    open through proxies and load balancers that close quiet connections, and to
    push the response headers out before the first real event.
    """
    return f": {text}\n\n"


async def sse_stream(
    events: AsyncIterator[BaseModel],
    event_name: Mapping[type[BaseModel], str] | None = None,
) -> AsyncIterator[str]:
    """Encode a stream of models as SSE frames.

    Args:
        events: Source of events. Consumed once.
        event_name: Optional map from model type to event name. A model with a
            ``type`` attribute supplies its own name, which is the normal case;
            this exists for models that do not.

    Yields:
        Encoded frames, beginning with a comment that flushes the headers.
    """
    # Sent before anything else so the client's connection is established and
    # its `onopen` fires immediately, rather than waiting for a first event that
    # may be seconds away while a model thinks.
    yield format_comment("stream open")

    async for event in events:
        name = (event_name or {}).get(type(event)) or str(getattr(event, "type", "message"))
        yield format_event(name, event)
