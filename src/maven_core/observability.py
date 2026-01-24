"""Structured logging and observability utilities.

Provides structured logging with context propagation, request tracing,
and metric collection hooks.
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

# Context variables for request-scoped data
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)


class LogLevel(str, Enum):
    """Log levels matching Python's logging module."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogContext:
    """Context data to include with every log entry."""

    request_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def current(cls) -> "LogContext":
        """Get current context from context variables."""
        return cls(
            request_id=request_id_var.get(),
            tenant_id=tenant_id_var.get(),
            user_id=user_id_var.get(),
            session_id=session_id_var.get(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        if self.request_id:
            result["request_id"] = self.request_id
        if self.tenant_id:
            result["tenant_id"] = self.tenant_id
        if self.user_id:
            result["user_id"] = self.user_id
        if self.session_id:
            result["session_id"] = self.session_id
        result.update(self.extra)
        return result


@dataclass
class LogEntry:
    """A structured log entry."""

    level: LogLevel
    message: str
    timestamp: str
    logger: str
    context: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    duration_ms: float | None = None

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = {
            "level": self.level.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "logger": self.logger,
        }
        if self.context:
            data["context"] = self.context
        if self.error:
            data["error"] = self.error
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        return json.dumps(data)


class StructuredFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON."""
        # Get context from context variables
        context = LogContext.current().to_dict()

        # Add any extra attributes from the record
        if hasattr(record, "context") and isinstance(record.context, dict):
            context.update(record.context)

        # Build error info if exception present
        error = None
        if record.exc_info:
            error = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
            }

        # Get duration if present
        duration_ms = getattr(record, "duration_ms", None)

        entry = LogEntry(
            level=LogLevel(record.levelname),
            message=record.getMessage(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            logger=record.name,
            context=context,
            error=error,
            duration_ms=duration_ms,
        )

        return entry.to_json()


class StructuredLogger:
    """Wrapper around Python logging with structured output.

    Example:
        logger = StructuredLogger("maven_core.agent")
        logger.info("Chat started", context={"user_id": "123"})
        logger.error("Failed to process", error=exception)
    """

    def __init__(self, name: str, level: LogLevel = LogLevel.INFO) -> None:
        """Initialize structured logger.

        Args:
            name: Logger name (typically module name)
            level: Minimum log level
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level.value)

        # Add handler with structured formatter if not already present
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(StructuredFormatter())
            self.logger.addHandler(handler)

    def _log(
        self,
        level: LogLevel,
        message: str,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Internal log method."""
        extra = {}
        if context:
            extra["context"] = context
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms

        log_func = getattr(self.logger, level.value.lower())
        if error:
            log_func(message, exc_info=(type(error), error, error.__traceback__), extra=extra)
        else:
            log_func(message, extra=extra)

    def debug(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log at DEBUG level."""
        self._log(LogLevel.DEBUG, message, context, duration_ms=duration_ms)

    def info(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log at INFO level."""
        self._log(LogLevel.INFO, message, context, duration_ms=duration_ms)

    def warning(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log at WARNING level."""
        self._log(LogLevel.WARNING, message, context, error, duration_ms)

    def error(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log at ERROR level."""
        self._log(LogLevel.ERROR, message, context, error, duration_ms)

    def critical(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log at CRITICAL level."""
        self._log(LogLevel.CRITICAL, message, context, error, duration_ms)


class RequestContext:
    """Context manager for request-scoped logging context.

    Example:
        async with RequestContext(
            request_id="req-123",
            tenant_id="tenant-456",
            user_id="user-789",
        ):
            # All logs in this block will include context
            logger.info("Processing request")
    """

    def __init__(
        self,
        request_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Initialize request context.

        Args:
            request_id: Unique request identifier
            tenant_id: Tenant identifier
            user_id: User identifier
            session_id: Session identifier
        """
        self.request_id = request_id or str(uuid.uuid4())
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id
        # Store (var, token) tuples so we can reset properly
        self._tokens: list[tuple[ContextVar, Any]] = []

    def __enter__(self) -> "RequestContext":
        """Set context variables."""
        self._tokens.append((request_id_var, request_id_var.set(self.request_id)))
        if self.tenant_id:
            self._tokens.append((tenant_id_var, tenant_id_var.set(self.tenant_id)))
        if self.user_id:
            self._tokens.append((user_id_var, user_id_var.set(self.user_id)))
        if self.session_id:
            self._tokens.append((session_id_var, session_id_var.set(self.session_id)))
        return self

    def __exit__(self, *args: Any) -> None:
        """Reset context variables to their previous values."""
        for var, token in self._tokens:
            var.reset(token)

    async def __aenter__(self) -> "RequestContext":
        """Async context manager entry."""
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        self.__exit__(*args)


class Timer:
    """Context manager for timing operations.

    Example:
        with Timer() as t:
            await do_operation()
        logger.info("Operation complete", duration_ms=t.duration_ms)
    """

    def __init__(self) -> None:
        """Initialize timer."""
        self.start_time: float = 0
        self.end_time: float = 0

    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        return (self.end_time - self.start_time) * 1000

    def __enter__(self) -> "Timer":
        """Start timer."""
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        """Stop timer."""
        self.end_time = time.perf_counter()

    async def __aenter__(self) -> "Timer":
        """Async start timer."""
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        """Async stop timer."""
        self.__exit__(*args)


# Metric collection hook type
MetricCallback = Callable[[str, float, dict[str, Any]], None]

_metric_callbacks: list[MetricCallback] = []


def register_metric_callback(callback: MetricCallback) -> None:
    """Register a callback to receive metric events.

    Args:
        callback: Function(name, value, labels) to call on metrics
    """
    _metric_callbacks.append(callback)


def emit_metric(name: str, value: float, labels: dict[str, Any] | None = None) -> None:
    """Emit a metric to all registered callbacks.

    Args:
        name: Metric name
        value: Metric value
        labels: Optional labels/dimensions
    """
    labels = labels or {}

    # Add context from context variables
    context = LogContext.current()
    if context.tenant_id:
        labels.setdefault("tenant_id", context.tenant_id)

    for callback in _metric_callbacks:
        try:
            callback(name, value, labels)
        except Exception:
            pass  # Don't let metric errors affect main flow


def emit_counter(name: str, labels: dict[str, Any] | None = None) -> None:
    """Emit a counter metric (increment by 1)."""
    emit_metric(name, 1.0, labels)


def emit_timer(name: str, duration_ms: float, labels: dict[str, Any] | None = None) -> None:
    """Emit a timer metric."""
    emit_metric(name, duration_ms, labels)


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    format: str = "json",
) -> None:
    """Configure root logger for the application.

    Args:
        level: Minimum log level
        format: Output format ("json" or "text")
    """
    root_logger = logging.getLogger("maven_core")
    root_logger.setLevel(level.value)

    # Remove existing handlers
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if format == "json":
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))

    root_logger.addHandler(handler)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger for a module.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structured logger
    """
    return StructuredLogger(name)
