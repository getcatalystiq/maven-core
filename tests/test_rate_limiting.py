"""Tests for rate limiting module."""

import pytest

from maven_core.rate_limiting import (
    CompositeRateLimiter,
    FixedWindowRateLimiter,
    RateLimiterFactory,
    RateLimitResult,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)


class TestSlidingWindowRateLimiter:
    """Tests for SlidingWindowRateLimiter."""

    @pytest.mark.asyncio
    async def test_allows_under_limit(self) -> None:
        """Allows requests under the limit."""
        limiter = SlidingWindowRateLimiter(limit=10, window_seconds=60)

        for _ in range(5):
            result = await limiter.check("key")
            assert result.is_allowed
            assert result.result == RateLimitResult.ALLOWED

    @pytest.mark.asyncio
    async def test_blocks_over_limit(self) -> None:
        """Blocks requests over the limit."""
        limiter = SlidingWindowRateLimiter(limit=3, window_seconds=60)

        # Use up the limit
        for _ in range(3):
            result = await limiter.check("key")
            assert result.is_allowed

        # Next request should be blocked
        result = await limiter.check("key")
        assert not result.is_allowed
        assert result.result == RateLimitResult.DENIED
        assert result.retry_after is not None
        assert result.retry_after > 0

    @pytest.mark.asyncio
    async def test_remaining_decreases(self) -> None:
        """Remaining count decreases with each request."""
        limiter = SlidingWindowRateLimiter(limit=5, window_seconds=60)

        result1 = await limiter.check("key")
        assert result1.remaining == 4

        result2 = await limiter.check("key")
        assert result2.remaining == 3

    @pytest.mark.asyncio
    async def test_different_keys_independent(self) -> None:
        """Different keys have independent limits."""
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)

        # Use up limit for key1
        await limiter.check("key1")
        await limiter.check("key1")
        result1 = await limiter.check("key1")
        assert not result1.is_allowed

        # key2 should still be allowed
        result2 = await limiter.check("key2")
        assert result2.is_allowed

    @pytest.mark.asyncio
    async def test_reset_clears_limit(self) -> None:
        """Reset clears the rate limit."""
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)

        await limiter.check("key")
        await limiter.check("key")
        result = await limiter.check("key")
        assert not result.is_allowed

        await limiter.reset("key")

        result = await limiter.check("key")
        assert result.is_allowed


class TestTokenBucketRateLimiter:
    """Tests for TokenBucketRateLimiter."""

    @pytest.mark.asyncio
    async def test_allows_burst(self) -> None:
        """Allows requests up to burst limit."""
        limiter = TokenBucketRateLimiter(rate=1, burst=10)

        for _ in range(10):
            result = await limiter.check("key")
            assert result.is_allowed

    @pytest.mark.asyncio
    async def test_blocks_after_burst(self) -> None:
        """Blocks after burst is exhausted."""
        limiter = TokenBucketRateLimiter(rate=1, burst=3)

        # Exhaust burst
        for _ in range(3):
            await limiter.check("key")

        # Should be blocked
        result = await limiter.check("key")
        assert not result.is_allowed
        assert result.retry_after is not None

    @pytest.mark.asyncio
    async def test_remaining_reflects_tokens(self) -> None:
        """Remaining reflects available tokens."""
        limiter = TokenBucketRateLimiter(rate=1, burst=10)

        result = await limiter.check("key")
        assert result.remaining == 9

    @pytest.mark.asyncio
    async def test_reset_refills_bucket(self) -> None:
        """Reset refills the bucket."""
        limiter = TokenBucketRateLimiter(rate=1, burst=3)

        # Exhaust bucket
        for _ in range(3):
            await limiter.check("key")

        await limiter.reset("key")

        result = await limiter.check("key")
        assert result.is_allowed


class TestFixedWindowRateLimiter:
    """Tests for FixedWindowRateLimiter."""

    @pytest.mark.asyncio
    async def test_allows_under_limit(self) -> None:
        """Allows requests under the limit."""
        limiter = FixedWindowRateLimiter(limit=10, window_seconds=60)

        for _ in range(5):
            result = await limiter.check("key")
            assert result.is_allowed

    @pytest.mark.asyncio
    async def test_blocks_over_limit(self) -> None:
        """Blocks requests over the limit."""
        limiter = FixedWindowRateLimiter(limit=3, window_seconds=60)

        for _ in range(3):
            await limiter.check("key")

        result = await limiter.check("key")
        assert not result.is_allowed

    @pytest.mark.asyncio
    async def test_reset_clears_count(self) -> None:
        """Reset clears the request count."""
        limiter = FixedWindowRateLimiter(limit=2, window_seconds=60)

        await limiter.check("key")
        await limiter.check("key")

        await limiter.reset("key")

        result = await limiter.check("key")
        assert result.is_allowed


class TestCompositeRateLimiter:
    """Tests for CompositeRateLimiter."""

    @pytest.mark.asyncio
    async def test_allows_when_all_allow(self) -> None:
        """Allows when all limiters allow."""
        limiter = CompositeRateLimiter([
            SlidingWindowRateLimiter(limit=10, window_seconds=1),
            SlidingWindowRateLimiter(limit=100, window_seconds=60),
        ])

        result = await limiter.check("key")
        assert result.is_allowed

    @pytest.mark.asyncio
    async def test_blocks_when_any_blocks(self) -> None:
        """Blocks when any limiter blocks."""
        # First limiter allows 10/sec, second allows 2/min
        limiter = CompositeRateLimiter([
            SlidingWindowRateLimiter(limit=10, window_seconds=1),
            SlidingWindowRateLimiter(limit=2, window_seconds=60),
        ])

        # First two allowed
        await limiter.check("key")
        await limiter.check("key")

        # Third blocked by minute limiter
        result = await limiter.check("key")
        assert not result.is_allowed

    @pytest.mark.asyncio
    async def test_reset_resets_all(self) -> None:
        """Reset resets all limiters."""
        limiter = CompositeRateLimiter([
            SlidingWindowRateLimiter(limit=2, window_seconds=60),
            SlidingWindowRateLimiter(limit=2, window_seconds=60),
        ])

        await limiter.check("key")
        await limiter.check("key")

        await limiter.reset("key")

        result = await limiter.check("key")
        assert result.is_allowed


class TestRateLimiterFactory:
    """Tests for RateLimiterFactory."""

    def test_creates_sliding_window(self) -> None:
        """Creates sliding window limiter."""
        limiter = RateLimiterFactory.create({
            "algorithm": "sliding_window",
            "limit": 100,
            "window_seconds": 60,
        })
        assert isinstance(limiter, SlidingWindowRateLimiter)

    def test_creates_token_bucket(self) -> None:
        """Creates token bucket limiter."""
        limiter = RateLimiterFactory.create({
            "algorithm": "token_bucket",
            "rate": 10,
            "burst": 50,
        })
        assert isinstance(limiter, TokenBucketRateLimiter)

    def test_creates_fixed_window(self) -> None:
        """Creates fixed window limiter."""
        limiter = RateLimiterFactory.create({
            "algorithm": "fixed_window",
            "limit": 100,
            "window_seconds": 60,
        })
        assert isinstance(limiter, FixedWindowRateLimiter)

    def test_defaults_to_sliding_window(self) -> None:
        """Defaults to sliding window when algorithm not specified."""
        limiter = RateLimiterFactory.create({
            "limit": 100,
            "window_seconds": 60,
        })
        assert isinstance(limiter, SlidingWindowRateLimiter)

    def test_unknown_algorithm_raises(self) -> None:
        """Unknown algorithm raises ValueError."""
        with pytest.raises(ValueError, match="Unknown rate limit algorithm"):
            RateLimiterFactory.create({"algorithm": "unknown"})

    def test_register_custom_algorithm(self) -> None:
        """Can register custom algorithm."""

        class CustomLimiter:
            def __init__(self, custom_param: str) -> None:
                self.custom_param = custom_param

        RateLimiterFactory.register("custom", CustomLimiter)

        limiter = RateLimiterFactory.create({
            "algorithm": "custom",
            "custom_param": "test",
        })

        assert isinstance(limiter, CustomLimiter)
        assert limiter.custom_param == "test"
