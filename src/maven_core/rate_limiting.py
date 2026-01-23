"""Rate limiting interfaces and implementations.

Provides extensible rate limiting with multiple algorithms and backends.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class RateLimitResult(Enum):
    """Result of a rate limit check."""

    ALLOWED = "allowed"
    DENIED = "denied"


@dataclass
class RateLimitInfo:
    """Information about rate limit status."""

    result: RateLimitResult
    limit: int
    remaining: int
    reset_at: float  # Unix timestamp
    retry_after: float | None = None  # Seconds until allowed

    @property
    def is_allowed(self) -> bool:
        """Check if request is allowed."""
        return self.result == RateLimitResult.ALLOWED


class RateLimiter(Protocol):
    """Protocol for rate limiter implementations."""

    async def check(self, key: str) -> RateLimitInfo:
        """Check if request is allowed.

        Args:
            key: Identifier for the rate limit bucket (e.g., user_id, IP)

        Returns:
            Rate limit info including whether allowed
        """
        ...

    async def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        ...


class SlidingWindowRateLimiter:
    """Sliding window rate limiter.

    Uses an in-memory sliding window for accurate rate limiting.
    For production, consider using a distributed backend (Redis).

    Example:
        limiter = SlidingWindowRateLimiter(limit=100, window_seconds=60)
        info = await limiter.check("user-123")
        if not info.is_allowed:
            raise RateLimitExceeded(info.retry_after)
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int = 60,
    ) -> None:
        """Initialize rate limiter.

        Args:
            limit: Maximum requests per window
            window_seconds: Window size in seconds
        """
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    async def check(self, key: str) -> RateLimitInfo:
        """Check if request is allowed under rate limit."""
        now = time.time()
        window_start = now - self.window_seconds

        # Get requests in current window
        if key not in self._requests:
            self._requests[key] = []

        # Clean old requests
        self._requests[key] = [
            t for t in self._requests[key]
            if t > window_start
        ]

        requests_in_window = len(self._requests[key])
        remaining = max(0, self.limit - requests_in_window)

        # Calculate reset time (when oldest request exits window)
        if self._requests[key]:
            oldest = min(self._requests[key])
            reset_at = oldest + self.window_seconds
        else:
            reset_at = now + self.window_seconds

        if requests_in_window >= self.limit:
            # Rate limited
            retry_after = reset_at - now
            return RateLimitInfo(
                result=RateLimitResult.DENIED,
                limit=self.limit,
                remaining=0,
                reset_at=reset_at,
                retry_after=max(0, retry_after),
            )

        # Allowed - record request
        self._requests[key].append(now)

        return RateLimitInfo(
            result=RateLimitResult.ALLOWED,
            limit=self.limit,
            remaining=remaining - 1,  # Account for this request
            reset_at=reset_at,
        )

    async def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        self._requests.pop(key, None)


class TokenBucketRateLimiter:
    """Token bucket rate limiter.

    Allows bursts up to the bucket size while maintaining
    a steady rate of requests over time.

    Example:
        limiter = TokenBucketRateLimiter(
            rate=10,  # 10 tokens per second
            burst=50,  # Allow bursts up to 50
        )
    """

    def __init__(
        self,
        rate: float,
        burst: int,
    ) -> None:
        """Initialize token bucket.

        Args:
            rate: Tokens added per second
            burst: Maximum bucket capacity
        """
        self.rate = rate
        self.burst = burst
        self._buckets: dict[str, tuple[float, float]] = {}  # (tokens, last_update)

    async def check(self, key: str) -> RateLimitInfo:
        """Check if request is allowed, consuming a token."""
        now = time.time()

        # Get or create bucket
        if key in self._buckets:
            tokens, last_update = self._buckets[key]
            # Add tokens based on elapsed time
            elapsed = now - last_update
            tokens = min(self.burst, tokens + elapsed * self.rate)
        else:
            tokens = float(self.burst)
            last_update = now

        if tokens < 1:
            # Not enough tokens
            wait_time = (1 - tokens) / self.rate
            return RateLimitInfo(
                result=RateLimitResult.DENIED,
                limit=self.burst,
                remaining=0,
                reset_at=now + wait_time,
                retry_after=wait_time,
            )

        # Consume token
        tokens -= 1
        self._buckets[key] = (tokens, now)

        return RateLimitInfo(
            result=RateLimitResult.ALLOWED,
            limit=self.burst,
            remaining=int(tokens),
            reset_at=now + (self.burst - tokens) / self.rate,
        )

    async def reset(self, key: str) -> None:
        """Reset bucket to full capacity."""
        self._buckets[key] = (float(self.burst), time.time())


class FixedWindowRateLimiter:
    """Fixed window rate limiter.

    Simple and efficient but may allow up to 2x the limit
    at window boundaries.

    Example:
        limiter = FixedWindowRateLimiter(limit=100, window_seconds=60)
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int = 60,
    ) -> None:
        """Initialize rate limiter.

        Args:
            limit: Maximum requests per window
            window_seconds: Window size in seconds
        """
        self.limit = limit
        self.window_seconds = window_seconds
        self._counters: dict[str, tuple[int, int]] = {}  # (count, window_start)

    def _get_window(self, now: float) -> int:
        """Get current window ID."""
        return int(now // self.window_seconds)

    async def check(self, key: str) -> RateLimitInfo:
        """Check if request is allowed under rate limit."""
        now = time.time()
        current_window = self._get_window(now)
        window_start = current_window * self.window_seconds
        reset_at = window_start + self.window_seconds

        # Get or create counter for current window
        if key in self._counters:
            count, counter_window = self._counters[key]
            if counter_window != current_window:
                # New window, reset counter
                count = 0
        else:
            count = 0

        remaining = max(0, self.limit - count)

        if count >= self.limit:
            # Rate limited
            return RateLimitInfo(
                result=RateLimitResult.DENIED,
                limit=self.limit,
                remaining=0,
                reset_at=reset_at,
                retry_after=reset_at - now,
            )

        # Allowed - increment counter
        self._counters[key] = (count + 1, current_window)

        return RateLimitInfo(
            result=RateLimitResult.ALLOWED,
            limit=self.limit,
            remaining=remaining - 1,
            reset_at=reset_at,
        )

    async def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        self._counters.pop(key, None)


class CompositeRateLimiter:
    """Combines multiple rate limiters.

    Useful for implementing tiered rate limits (e.g., per-second
    and per-day limits).

    Example:
        limiter = CompositeRateLimiter([
            SlidingWindowRateLimiter(limit=10, window_seconds=1),   # 10/sec
            SlidingWindowRateLimiter(limit=1000, window_seconds=3600),  # 1000/hour
        ])
    """

    def __init__(self, limiters: list[RateLimiter]) -> None:
        """Initialize with list of rate limiters.

        Args:
            limiters: Rate limiters to check in order
        """
        self.limiters = limiters

    async def check(self, key: str) -> RateLimitInfo:
        """Check all limiters, deny if any deny.

        Returns the most restrictive result.
        """
        results: list[RateLimitInfo] = []

        for limiter in self.limiters:
            result = await limiter.check(key)
            results.append(result)
            if not result.is_allowed:
                return result

        # All allowed - return with minimum remaining
        min_remaining = min(r.remaining for r in results)
        earliest_reset = min(r.reset_at for r in results)
        max_limit = max(r.limit for r in results)

        return RateLimitInfo(
            result=RateLimitResult.ALLOWED,
            limit=max_limit,
            remaining=min_remaining,
            reset_at=earliest_reset,
        )

    async def reset(self, key: str) -> None:
        """Reset all limiters for a key."""
        for limiter in self.limiters:
            await limiter.reset(key)


class RateLimiterFactory:
    """Factory for creating rate limiters from configuration.

    Example:
        factory = RateLimiterFactory()
        limiter = factory.create({
            "algorithm": "sliding_window",
            "limit": 100,
            "window_seconds": 60,
        })
    """

    _algorithms = {
        "sliding_window": SlidingWindowRateLimiter,
        "token_bucket": TokenBucketRateLimiter,
        "fixed_window": FixedWindowRateLimiter,
    }

    @classmethod
    def create(cls, config: dict) -> RateLimiter:
        """Create rate limiter from config.

        Args:
            config: Rate limiter configuration with "algorithm" key

        Returns:
            Configured rate limiter instance
        """
        algorithm = config.get("algorithm", "sliding_window")
        limiter_class = cls._algorithms.get(algorithm)

        if limiter_class is None:
            raise ValueError(f"Unknown rate limit algorithm: {algorithm}")

        # Extract kwargs for the limiter
        kwargs = {k: v for k, v in config.items() if k != "algorithm"}
        return limiter_class(**kwargs)

    @classmethod
    def register(cls, name: str, limiter_class: type) -> None:
        """Register a custom rate limiter algorithm.

        Args:
            name: Algorithm name
            limiter_class: Rate limiter class
        """
        cls._algorithms[name] = limiter_class
