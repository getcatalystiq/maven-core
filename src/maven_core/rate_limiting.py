"""Rate limiting with sliding window algorithm.

Provides simple, accurate rate limiting with optional tiered limits.
"""

import time
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
        max_keys: int = 10000,
    ) -> None:
        """Initialize rate limiter.

        Args:
            limit: Maximum requests per window
            window_seconds: Window size in seconds
            max_keys: Maximum number of keys to track (for memory bounds)
        """
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._requests: dict[str, list[float]] = {}
        self._last_cleanup = time.time()

    async def check(self, key: str) -> RateLimitInfo:
        """Check if request is allowed under rate limit."""
        now = time.time()
        window_start = now - self.window_seconds

        # Periodic cleanup of expired keys to prevent unbounded memory growth
        if now - self._last_cleanup > self.window_seconds:
            await self._cleanup_expired_keys()

        # Get requests in current window
        if key not in self._requests:
            self._requests[key] = []

        # Clean old requests for this key
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

    async def _cleanup_expired_keys(self) -> None:
        """Remove keys with no recent requests to bound memory usage."""
        now = time.time()
        window_start = now - self.window_seconds
        self._last_cleanup = now

        # Find keys with no requests in current window
        expired_keys = [
            key for key, requests in self._requests.items()
            if not requests or max(requests) < window_start
        ]

        # Remove expired keys
        for key in expired_keys:
            del self._requests[key]

        # If still over max_keys, evict oldest keys
        if len(self._requests) > self.max_keys:
            # Sort by most recent request, keep most active
            sorted_keys = sorted(
                self._requests.keys(),
                key=lambda k: max(self._requests[k]) if self._requests[k] else 0,
            )
            for key in sorted_keys[:len(sorted_keys) - self.max_keys]:
                del self._requests[key]

    async def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        self._requests.pop(key, None)


class CompositeRateLimiter:
    """Combines multiple rate limiters for tiered limits.

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


# Convenience alias (use different name to avoid shadowing Protocol)
DefaultRateLimiter = SlidingWindowRateLimiter
