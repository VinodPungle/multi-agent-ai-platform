"""Structured logging bootstrap.

Milestone 01 acceptance criterion: "Logging and tracing initialize successfully".

Logging is verified by parsing what actually reaches stdout. Asserting on
structlog's configuration object would pass while the output stayed broken.
"""

from __future__ import annotations

import json
import logging

import pytest

from agent_platform.configuration.settings import LoggingSettings
from agent_platform.telemetry.logging import (
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
)
from agent_platform_shared import correlation_scope

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_log_context() -> None:
    """Context-bound fields must not leak between tests."""
    clear_log_context()


def _emitted_records(captured: str) -> list[dict[str, object]]:
    """Parse the JSON records from captured stdout."""
    return [json.loads(line) for line in captured.splitlines() if line.startswith("{")]


class TestJsonRendering:
    """Machine-parsable output is required outside development."""

    def test_records_are_valid_json_with_the_expected_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        get_logger("test").info("something.happened", agent_id="chat-agent")

        records = _emitted_records(capsys.readouterr().out)
        assert len(records) == 1
        assert records[0]["event"] == "something.happened"
        assert records[0]["level"] == "info"
        assert records[0]["logger"] == "test"
        assert records[0]["agent_id"] == "chat-agent"
        assert records[0]["timestamp"]

    def test_console_renderer_produces_human_readable_output(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="console"))

        get_logger("test").info("readable.event")

        output = capsys.readouterr().out
        assert "readable.event" in output
        assert not output.strip().startswith("{")


class TestLevelFiltering:
    """A level that does not filter is a level that costs money for nothing."""

    def test_records_below_the_configured_level_are_dropped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="WARNING", renderer="json"))
        logger = get_logger("test")

        logger.debug("dropped.debug")
        logger.info("dropped.info")
        logger.warning("kept.warning")

        events = [record["event"] for record in _emitted_records(capsys.readouterr().out)]
        assert events == ["kept.warning"]


class TestCorrelationEnrichment:
    """No call site should have to remember to pass the ids."""

    def test_ambient_ids_are_injected_automatically(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        with correlation_scope(correlation_id="corr-abc", request_id="req-xyz"):
            get_logger("test").info("inside.scope")

        record = _emitted_records(capsys.readouterr().out)[0]
        assert record["correlation_id"] == "corr-abc"
        assert record["request_id"] == "req-xyz"

    def test_absent_ids_are_omitted_rather_than_null(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Startup records have no request to belong to."""
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        get_logger("test").info("outside.scope")

        record = _emitted_records(capsys.readouterr().out)[0]
        assert "correlation_id" not in record
        assert "request_id" not in record

    def test_bound_context_appears_on_later_records(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        bind_log_context(conversation_id="conv-1")
        get_logger("test").info("with.context")
        clear_log_context()
        get_logger("test").info("without.context")

        records = _emitted_records(capsys.readouterr().out)
        assert records[0]["conversation_id"] == "conv-1"
        assert "conversation_id" not in records[1]


class TestExceptionRendering:
    """An unserialisable exception object would silently drop the record."""

    def test_traceback_is_rendered_into_the_record(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        try:
            message = "deliberate failure"
            raise ValueError(message)
        except ValueError:
            get_logger("test").exception("operation.failed")

        record = _emitted_records(capsys.readouterr().out)[0]
        assert record["event"] == "operation.failed"
        assert "ValueError" in str(record.get("exception", ""))
        assert "deliberate failure" in str(record.get("exception", ""))


class TestStandardLibraryIntegration:
    """Third-party libraries must not emit a second, unparsable format."""

    def test_stdlib_logging_flows_through_the_same_pipeline(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        logging.getLogger("third_party.library").warning("legacy style message")

        records = _emitted_records(capsys.readouterr().out)
        assert records[0]["event"] == "legacy style message"
        assert records[0]["logger"] == "third_party.library"

    def test_reconfiguring_does_not_duplicate_records(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Appending a handler instead of replacing it doubles log volume."""
        configure_logging(LoggingSettings(level="INFO", renderer="json"))
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        get_logger("test").info("emitted.once")

        assert len(_emitted_records(capsys.readouterr().out)) == 1


class TestSourceLocation:
    """Useful locally, costly in volume — so it is opt-in."""

    def test_callsite_fields_are_added_when_enabled(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="json", include_source=True))

        get_logger("test").info("located.event")

        record = _emitted_records(capsys.readouterr().out)[0]
        assert "module" in record
        assert "func_name" in record
        assert "lineno" in record

    def test_callsite_fields_are_absent_by_default(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(LoggingSettings(level="INFO", renderer="json"))

        get_logger("test").info("unlocated.event")

        assert "module" not in _emitted_records(capsys.readouterr().out)[0]
