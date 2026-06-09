import pytest
from limits import RateLimitItemPerSecond
from limits.errors import StorageError
from limits.storage import MemoryStorage, storage_from_string

from falcon_rate_limiter.constants import (
    PRIMARY_STORAGE_RECOVERED_LOG_MESSAGE,
    PRIMARY_STORAGE_STILL_UNAVAILABLE_LOG_MESSAGE,
)
from falcon_rate_limiter._storage import StorageController


class FlakyMemoryStorage(MemoryStorage):
    """Memory storage that can fail request hits while still supporting recovery."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_hits = False
        self.available = True

    def check(self) -> bool:
        return self.available

    def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        if self.fail_hits:
            raise StorageError(RuntimeError("simulated storage outage"))
        return super().incr(key, expiry, amount=amount)


def test_storage_controller_rejects_storage_and_storage_uri_together() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        StorageController(storage=MemoryStorage(), storage_uri="memory://")


@pytest.mark.parametrize(
    ("recovery_backoff_seconds", "max_recovery_backoff_seconds", "message"),
    [
        (-1.0, 60.0, "must be >= 0"),
        (2.0, 1.0, "must be >="),
    ],
)
def test_storage_controller_rejects_invalid_recovery_backoff_configuration(
    recovery_backoff_seconds: float,
    max_recovery_backoff_seconds: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        StorageController(
            recovery_backoff_seconds=recovery_backoff_seconds,
            max_recovery_backoff_seconds=max_recovery_backoff_seconds,
        )


def test_storage_controller_uses_primary_limiter_by_default() -> None:
    controller = StorageController(storage=MemoryStorage())

    assert controller.limiter_for_enforcement() is controller.current_limiter


def test_storage_controller_does_not_activate_fallback_for_memory_storage() -> None:
    controller = StorageController(storage=MemoryStorage())

    activated = controller.activate_fallback_storage_for_error(
        StorageError(RuntimeError("simulated storage outage"))
    )

    assert activated is False


def test_storage_controller_falls_back_after_primary_error_and_recovers() -> None:
    storage = FlakyMemoryStorage()
    controller = StorageController(
        storage=storage,
        recovery_backoff_seconds=0.0,
        max_recovery_backoff_seconds=0.0,
    )
    primary_limiter = controller.current_limiter

    activated = controller.activate_fallback_storage_for_error(
        StorageError(RuntimeError("simulated storage outage"))
    )

    assert activated is True
    fallback_limiter = controller.current_limiter
    assert fallback_limiter is not primary_limiter

    storage.available = False
    assert controller.limiter_for_enforcement() is fallback_limiter

    storage.available = True
    assert controller.limiter_for_enforcement() is primary_limiter


def test_storage_controller_logs_failed_recovery_probe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = FlakyMemoryStorage()
    controller = StorageController(
        storage=storage,
        recovery_backoff_seconds=0.0,
        max_recovery_backoff_seconds=0.0,
    )
    controller.activate_fallback_storage_for_error(
        StorageError(RuntimeError("simulated storage outage"))
    )

    storage.available = False
    with caplog.at_level("WARNING", logger="falcon-rate-limiter"):
        controller.limiter_for_enforcement()

    assert PRIMARY_STORAGE_STILL_UNAVAILABLE_LOG_MESSAGE in caplog.text


def test_storage_controller_logs_primary_recovery(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = FlakyMemoryStorage()
    controller = StorageController(
        storage=storage,
        recovery_backoff_seconds=0.0,
        max_recovery_backoff_seconds=0.0,
    )
    controller.activate_fallback_storage_for_error(
        StorageError(RuntimeError("simulated storage outage"))
    )

    storage.available = True
    with caplog.at_level("INFO", logger="falcon-rate-limiter"):
        controller.limiter_for_enforcement()

    assert PRIMARY_STORAGE_RECOVERED_LOG_MESSAGE in caplog.text


def test_storage_controller_memory_uri_enforces_limits() -> None:
    controller = StorageController(storage_uri="memory://")
    limiter = controller.limiter_for_enforcement()
    item = RateLimitItemPerSecond(1)

    assert limiter.hit(item, "memory-uri-key") is True
    assert limiter.hit(item, "memory-uri-key") is False


def test_live_redis_storage_uri_enforces_limits_when_available() -> None:
    redis_uri = "redis://localhost:6379/15"
    redis_storage = storage_from_string(redis_uri)
    if not redis_storage.check():
        pytest.skip("Redis is not available on localhost:6379")

    redis_storage.reset()
    controller = StorageController(storage_uri=redis_uri)
    limiter = controller.limiter_for_enforcement()
    item = RateLimitItemPerSecond(1)

    try:
        assert limiter.hit(item, "redis-storage-key") is True
        assert limiter.hit(item, "redis-storage-key") is False
    finally:
        redis_storage.reset()
