"""Tests for observability module."""

import json
import logging
import time

import pytest

from maven_core.observability import (
    LogContext,
    LogEntry,
    LogLevel,
    RequestContext,
    StructuredFormatter,
    StructuredLogger,
    Timer,
    configure_logging,
    emit_counter,
    emit_metric,
    emit_timer,
    get_logger,
    register_metric_callback,
    request_id_var,
    session_id_var,
    tenant_id_var,
    user_id_var,
)


class TestLogContext:
    """Tests for LogContext."""

    def test_current_returns_empty_when_no_context(self) -> None:
        """Current returns empty context when no vars set."""
        context = LogContext.current()
        assert context.request_id is None
        assert context.tenant_id is None
        assert context.user_id is None
        assert context.session_id is None

    def test_to_dict_excludes_none_values(self) -> None:
        """to_dict excludes None values."""
        context = LogContext(
            request_id="req-123",
            tenant_id=None,
            user_id="user-456",
        )
        result = context.to_dict()

        assert result == {"request_id": "req-123", "user_id": "user-456"}
        assert "tenant_id" not in result

    def test_to_dict_includes_extra(self) -> None:
        """to_dict includes extra fields."""
        context = LogContext(
            request_id="req-123",
            extra={"custom": "value"},
        )
        result = context.to_dict()

        assert result["request_id"] == "req-123"
        assert result["custom"] == "value"


class TestLogEntry:
    """Tests for LogEntry."""

    def test_to_json_basic(self) -> None:
        """to_json produces valid JSON."""
        entry = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            timestamp="2024-01-01T00:00:00Z",
            logger="test",
        )
        result = json.loads(entry.to_json())

        assert result["level"] == "INFO"
        assert result["message"] == "Test message"
        assert result["timestamp"] == "2024-01-01T00:00:00Z"
        assert result["logger"] == "test"

    def test_to_json_with_context(self) -> None:
        """to_json includes context."""
        entry = LogEntry(
            level=LogLevel.INFO,
            message="Test",
            timestamp="2024-01-01T00:00:00Z",
            logger="test",
            context={"user_id": "user-123"},
        )
        result = json.loads(entry.to_json())

        assert result["context"]["user_id"] == "user-123"

    def test_to_json_with_error(self) -> None:
        """to_json includes error info."""
        entry = LogEntry(
            level=LogLevel.ERROR,
            message="Failed",
            timestamp="2024-01-01T00:00:00Z",
            logger="test",
            error={"type": "ValueError", "message": "bad value"},
        )
        result = json.loads(entry.to_json())

        assert result["error"]["type"] == "ValueError"
        assert result["error"]["message"] == "bad value"

    def test_to_json_with_duration(self) -> None:
        """to_json includes duration."""
        entry = LogEntry(
            level=LogLevel.INFO,
            message="Complete",
            timestamp="2024-01-01T00:00:00Z",
            logger="test",
            duration_ms=123.45,
        )
        result = json.loads(entry.to_json())

        assert result["duration_ms"] == 123.45


class TestStructuredFormatter:
    """Tests for StructuredFormatter."""

    def test_formats_as_json(self) -> None:
        """Formats log record as JSON."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed


class TestStructuredLogger:
    """Tests for StructuredLogger."""

    def test_info_logs_at_info_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Info method logs at INFO level."""
        logger = StructuredLogger("test.logger", LogLevel.DEBUG)

        with caplog.at_level(logging.INFO, logger="test.logger"):
            logger.info("Test message")

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "INFO"

    def test_error_logs_at_error_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Error method logs at ERROR level."""
        logger = StructuredLogger("test.error", LogLevel.DEBUG)

        with caplog.at_level(logging.ERROR, logger="test.error"):
            logger.error("Error message")

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "ERROR"


class TestRequestContext:
    """Tests for RequestContext."""

    def test_sets_context_vars(self) -> None:
        """Sets context variables within context."""
        with RequestContext(
            request_id="req-123",
            tenant_id="tenant-456",
            user_id="user-789",
            session_id="sess-abc",
        ):
            assert request_id_var.get() == "req-123"
            assert tenant_id_var.get() == "tenant-456"
            assert user_id_var.get() == "user-789"
            assert session_id_var.get() == "sess-abc"

    def test_generates_request_id_if_not_provided(self) -> None:
        """Generates request ID if not provided."""
        with RequestContext() as ctx:
            assert ctx.request_id is not None
            assert len(ctx.request_id) > 0

    @pytest.mark.asyncio
    async def test_works_as_async_context_manager(self) -> None:
        """Works as async context manager."""
        async with RequestContext(request_id="async-req") as ctx:
            assert ctx.request_id == "async-req"
            assert request_id_var.get() == "async-req"


class TestTimer:
    """Tests for Timer."""

    def test_measures_duration(self) -> None:
        """Measures elapsed time."""
        with Timer() as timer:
            time.sleep(0.05)

        assert timer.duration_ms >= 40  # Allow some variance
        assert timer.duration_ms < 200

    @pytest.mark.asyncio
    async def test_works_as_async_context_manager(self) -> None:
        """Works as async context manager."""
        import asyncio

        async with Timer() as timer:
            await asyncio.sleep(0.05)

        assert timer.duration_ms >= 40


class TestMetrics:
    """Tests for metric functions."""

    def test_register_and_emit_metric(self) -> None:
        """Register callback and emit metric."""
        received: list[tuple] = []

        def callback(name: str, value: float, labels: dict) -> None:
            received.append((name, value, labels))

        register_metric_callback(callback)

        emit_metric("test.metric", 42.5, {"key": "value"})

        assert len(received) > 0
        name, value, labels = received[-1]
        assert name == "test.metric"
        assert value == 42.5
        assert labels["key"] == "value"

    def test_emit_counter(self) -> None:
        """Emit counter increments by 1."""
        received: list[tuple] = []

        def callback(name: str, value: float, labels: dict) -> None:
            received.append((name, value, labels))

        register_metric_callback(callback)

        emit_counter("test.counter")

        name, value, _ = received[-1]
        assert name == "test.counter"
        assert value == 1.0

    def test_emit_timer(self) -> None:
        """Emit timer with duration."""
        received: list[tuple] = []

        def callback(name: str, value: float, labels: dict) -> None:
            received.append((name, value, labels))

        register_metric_callback(callback)

        emit_timer("test.timer", 123.45)

        name, value, _ = received[-1]
        assert name == "test.timer"
        assert value == 123.45


class TestConfigureLogging:
    """Tests for configure_logging."""

    def test_configures_root_logger(self) -> None:
        """Configures the root logger."""
        configure_logging(level=LogLevel.DEBUG, format="json")

        root = logging.getLogger("maven_core")
        assert root.level == logging.DEBUG

    def test_get_logger_returns_structured_logger(self) -> None:
        """get_logger returns StructuredLogger."""
        logger = get_logger("test.module")
        assert isinstance(logger, StructuredLogger)
