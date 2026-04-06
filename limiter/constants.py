"""Shared constants for user-visible limiter messages and storage events."""

DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE = "Rate limit exceeded"

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
