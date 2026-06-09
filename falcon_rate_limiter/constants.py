"""Shared constants for user-visible limiter messages and storage events."""

from limits.strategies import (
    FixedWindowRateLimiter,
    MovingWindowRateLimiter,
    SlidingWindowCounterRateLimiter,
)

FIXED_WINDOW_STRATEGY = "fixed-window"
MOVING_WINDOW_STRATEGY = "moving-window"
SLIDING_WINDOW_COUNTER_STRATEGY = "sliding-window-counter"

SupportedRateLimiterClass = type[
    FixedWindowRateLimiter | MovingWindowRateLimiter | SlidingWindowCounterRateLimiter
]

LIMITS_LIMITER_PER_STRATEGY: dict[str, SupportedRateLimiterClass] = {
    FIXED_WINDOW_STRATEGY: FixedWindowRateLimiter,
    MOVING_WINDOW_STRATEGY: MovingWindowRateLimiter,
    SLIDING_WINDOW_COUNTER_STRATEGY: SlidingWindowCounterRateLimiter,
}

DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE = "Rate limit exceeded"
EMPTY_METHODS_ERROR_MESSAGE = "methods must contain at least one HTTP method"
INVALID_LIMIT_COST_ERROR_MESSAGE = (
    "Invalid resolved limit cost value. It should be a positive integer."
)
INVALID_RATE_LIMIT_STRATEGY_ERROR_MESSAGE = f"Invalid rate limiting strategy. Supported strategies are: {FIXED_WINDOW_STRATEGY}, {MOVING_WINDOW_STRATEGY}, {SLIDING_WINDOW_COUNTER_STRATEGY}."
REDIS_EXTRA_REQUIRED_MESSAGE = (
    "Redis storage requires the optional Redis dependency. Install it with "
    '`pip install "falcon-rate-limiter[redis]"` or '
    '`uv add "falcon-rate-limiter[redis]"` before using a Redis storage URI.'
)

PRIMARY_STORAGE_UNAVAILABLE_MESSAGE = (
    "Primary storage is unavailable during initialization"
)
PRIMARY_STORAGE_FAILED_DURING_REQUEST_MESSAGE = (
    "Primary storage failed during request handling"
)
IN_MEMORY_FALLBACK_LOG_MESSAGE = "Switching rate limiter storage to in-memory fallback"
PRIMARY_STORAGE_RECOVERED_LOG_MESSAGE = (
    "Primary rate limiter storage recovered; restoring configured backend."
)
PRIMARY_STORAGE_STILL_UNAVAILABLE_LOG_MESSAGE = (
    "Primary rate limiter storage is still unavailable; next recovery probe in"
)
