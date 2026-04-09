"""Shared constants: default values, log message templates, and env var names."""

LOGGER_NAME = "falcon-rate-limiter"

DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE = "Rate limit exceeded"
RATE_LIMIT_EXCEEDED_LOG_MESSAGE = "Rate limit exceeded for key"
SWALLOWED_RATE_LIMIT_ERROR_LOG_MESSAGE = (
    "Failed to enforce rate limit. Swallowing error."
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

RATELIMIT_ENABLED_ENV = "RATELIMIT_ENABLED"
RATELIMIT_HEADERS_ENABLED_ENV = "RATELIMIT_HEADERS_ENABLED"
RATELIMIT_STORAGE_URL_ENV = "RATELIMIT_STORAGE_URL"
RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV = "RATELIMIT_LIMIT_UNDECORATED_ROUTES"
RATELIMIT_SWALLOW_ERRORS_ENV = "RATELIMIT_SWALLOW_ERRORS"
RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV = "RATELIMIT_RECOVERY_BACKOFF_SECONDS"
RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV = "RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS"
RATELIMIT_STRATEGY_ENV = "RATELIMIT_STRATEGY"

DEFAULT_STRATEGY = "fixed-window"
SUPPORTED_STRATEGIES = frozenset(
    {"fixed-window", "moving-window", "sliding-window-counter"}
)
INVALID_STRATEGY_MESSAGE = "Unknown rate limiting strategy {!r}. Supported: {}"
