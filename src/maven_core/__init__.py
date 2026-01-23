"""Maven Core - A modular framework for building AI agents."""

from maven_core.agent import Agent, ChatResponse, StreamChunk
from maven_core.caching import CachedLoader, SingleFlight, TTLCache
from maven_core.config import Config
from maven_core.observability import (
    LogLevel,
    RequestContext,
    StructuredLogger,
    Timer,
    configure_logging,
    emit_counter,
    emit_metric,
    emit_timer,
    get_logger,
    register_metric_callback,
)
from maven_core.rate_limiting import (
    CompositeRateLimiter,
    FixedWindowRateLimiter,
    RateLimiter,
    RateLimiterFactory,
    RateLimitInfo,
    RateLimitResult,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)

__version__ = "0.1.0"
__all__ = [
    # Core
    "Agent",
    "ChatResponse",
    "Config",
    "StreamChunk",
    # Caching
    "CachedLoader",
    "SingleFlight",
    "TTLCache",
    # Observability
    "LogLevel",
    "RequestContext",
    "StructuredLogger",
    "Timer",
    "configure_logging",
    "emit_counter",
    "emit_metric",
    "emit_timer",
    "get_logger",
    "register_metric_callback",
    # Rate Limiting
    "CompositeRateLimiter",
    "FixedWindowRateLimiter",
    "RateLimiter",
    "RateLimiterFactory",
    "RateLimitInfo",
    "RateLimitResult",
    "SlidingWindowRateLimiter",
    "TokenBucketRateLimiter",
]
