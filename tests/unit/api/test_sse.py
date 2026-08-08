"""Server-sent event encoding.

Every assertion here is a framing rule that, if broken, produces a stream which
looks fine in a unit test and hangs in a browser. They are cheap to pin and
expensive to debug from the symptom.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_platform.api.sse import (
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    format_comment,
    format_event,
    sse_stream,
)
from agent_platform.domain.chat import ChatDeltaEvent, ChatStartedEvent

pytestmark = pytest.mark.unit


class Payload(BaseModel):
    value: str


class TestFrameFormat:
    def test_a_frame_names_its_event(self) -> None:
        frame = format_event("delta", Payload(value="hi"))

        assert frame.startswith("event: delta\n")

    def test_a_frame_carries_its_payload_as_json(self) -> None:
        frame = format_event("delta", Payload(value="hi"))

        assert 'data: {"value":"hi"}' in frame

    def test_a_frame_ends_with_a_blank_line(self) -> None:
        """Without it the client buffers forever and nothing is ever delivered."""
        assert format_event("delta", Payload(value="hi")).endswith("\n\n")

    def test_a_newline_in_the_payload_does_not_break_framing(self) -> None:
        """A raw newline inside a `data:` line would end the field early."""
        frame = format_event("delta", Payload(value="line one\nline two"))

        body_lines = [line for line in frame.split("\n") if line.startswith("data: ")]
        assert len(body_lines) == 1
        assert "\\n" in body_lines[0]

    def test_a_comment_frame_carries_no_event(self) -> None:
        frame = format_comment("stream open")

        assert frame == ": stream open\n\n"
        assert "event:" not in frame


class TestHeaders:
    def test_the_media_type_is_the_sse_one(self) -> None:
        assert SSE_MEDIA_TYPE == "text/event-stream"

    def test_buffering_is_disabled_for_reverse_proxies(self) -> None:
        """nginx buffers proxied responses by default; SSE then arrives in one block."""
        assert SSE_HEADERS["X-Accel-Buffering"] == "no"

    def test_the_response_is_not_cached(self) -> None:
        assert "no-cache" in SSE_HEADERS["Cache-Control"]

    def test_transformation_is_disabled(self) -> None:
        """`no-transform` stops a proxy re-compressing and re-chunking the stream."""
        assert "no-transform" in SSE_HEADERS["Cache-Control"]


class TestStreamEncoding:
    async def test_the_stream_opens_with_a_comment(self) -> None:
        """Flushes the headers so the client's `onopen` fires before the first event."""

        async def events() -> object:
            yield ChatDeltaEvent(delta="hi")

        frames = [frame async for frame in sse_stream(events())]  # type: ignore[arg-type]

        assert frames[0].startswith(": ")

    async def test_each_event_is_named_by_its_type(self) -> None:
        async def events() -> object:
            yield ChatStartedEvent(conversation_id="c1", message_id="m1", model_id="m")
            yield ChatDeltaEvent(delta="hi")

        frames = [frame async for frame in sse_stream(events())]  # type: ignore[arg-type]

        assert "event: started" in frames[1]
        assert "event: delta" in frames[2]

    async def test_an_empty_stream_still_opens(self) -> None:
        """A client must connect successfully even when there is nothing to send."""

        async def events() -> object:
            return
            yield  # pragma: no cover - makes this an async generator

        frames = [frame async for frame in sse_stream(events())]  # type: ignore[arg-type]

        assert len(frames) == 1
