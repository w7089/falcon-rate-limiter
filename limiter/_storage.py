import logging
import time
from typing import cast

from limits.errors import StorageError
from limits.storage import MemoryStorage, Storage, storage_from_string
from limits.strategies import FixedWindowRateLimiter
from redis.exceptions import RedisError

from limiter.constants import (
    IN_MEMORY_FALLBACK_LOG_MESSAGE,
    PRIMARY_STORAGE_FAILED_DURING_REQUEST_MESSAGE,
    PRIMARY_STORAGE_RECOVERED_LOG_MESSAGE,
    PRIMARY_STORAGE_STILL_UNAVAILABLE_LOG_MESSAGE,
    PRIMARY_STORAGE_UNAVAILABLE_MESSAGE,
)

_STORAGE_LOGGER = logging.getLogger("falcon-rate-limiter")
STORAGE_BACKEND_EXCEPTIONS = (
    StorageError,
    RedisError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def _resolve_storage(
    storage: Storage | None,
    storage_uri: str | None,
) -> Storage:
    """Resolve the configured storage backend.

    Args:
        storage: Explicit ``limits`` storage instance to use.
        storage_uri: URI understood by ``limits.storage.storage_from_string``.

    Returns:
        A configured storage backend. Defaults to ``memory://`` when neither
        ``storage`` nor ``storage_uri`` is provided.

    Raises:
        ValueError: When both ``storage`` and ``storage_uri`` are provided.
    """
    if storage is not None and storage_uri is not None:
        raise ValueError("storage and storage_uri are mutually exclusive")
    if storage is not None:
        return storage
    if storage_uri is not None:
        return cast(Storage, storage_from_string(storage_uri))
    return cast(Storage, storage_from_string("memory://"))


class StorageController:
    """Manage primary storage, in-memory fallback, and recovery probing.

    Args:
        storage: Explicit ``limits`` storage instance to use.
        storage_uri: Storage URI to resolve via ``limits``.
        recovery_backoff_seconds: Initial delay before probing for recovery.
        max_recovery_backoff_seconds: Maximum recovery probe delay.

    Raises:
        ValueError: When storage configuration is invalid.
    """

    def __init__(
        self,
        storage: Storage | None = None,
        storage_uri: str | None = None,
        recovery_backoff_seconds: float = 1.0,
        max_recovery_backoff_seconds: float = 60.0,
    ) -> None:
        if recovery_backoff_seconds < 0:
            raise ValueError("recovery_backoff_seconds must be >= 0")
        if max_recovery_backoff_seconds < recovery_backoff_seconds:
            raise ValueError(
                "max_recovery_backoff_seconds must be >= recovery_backoff_seconds"
            )
        self._primary_storage = _resolve_storage(storage, storage_uri)
        self._fallback_storage: MemoryStorage | None = None
        self._primary_limiter = FixedWindowRateLimiter(self._primary_storage)
        self._fallback_limiter: FixedWindowRateLimiter | None = None
        self._recovery_backoff_seconds = recovery_backoff_seconds
        self._max_recovery_backoff_seconds = max_recovery_backoff_seconds
        self._current_recovery_backoff_seconds = recovery_backoff_seconds
        self._next_recovery_probe_at = 0.0
        self._using_fallback_storage = False

        if not self._is_memory_storage(
            self._primary_storage
        ) and not self._is_available(self._primary_storage):
            self._switch_to_fallback_storage(PRIMARY_STORAGE_UNAVAILABLE_MESSAGE)

    @property
    def current_limiter(self) -> FixedWindowRateLimiter:
        """Return the limiter that is currently active.

        Returns:
            The limiter currently bound to the selected storage backend.

        Raises:
            None.
        """
        if self._using_fallback_storage:
            if self._fallback_limiter is None:
                raise RuntimeError(
                    "Fallback limiter must exist while fallback storage is active"
                )
            return self._fallback_limiter
        return self._primary_limiter

    def limiter_for_enforcement(self) -> FixedWindowRateLimiter:
        """Return the rate limiter that should handle the current request.

        Returns:
            The primary limiter when it is available, otherwise the current
            in-memory fallback limiter.

        Raises:
            None.
        """
        self._restore_primary_storage_if_recovery_probe_is_due()
        return self.current_limiter

    def activate_fallback_storage_for_error(self, error: BaseException) -> bool:
        """Switch to fallback storage for a primary storage failure.

        Args:
            error: Storage exception raised while using the active limiter.

        Returns:
            ``True`` when fallback storage was activated and the caller should
            retry the rate-limit operation, otherwise ``False``.

        Raises:
            None.
        """
        if self._using_fallback_storage:
            # We already switched away from the primary backend, so there is no
            # second fallback target to activate for this request.
            return False

        if self._is_memory_storage(self._primary_storage):
            # The configured primary backend is already in-memory storage, so a
            # separate in-memory fallback would not change behavior.
            return False

        self._switch_to_fallback_storage(
            PRIMARY_STORAGE_FAILED_DURING_REQUEST_MESSAGE,
            error,
        )
        return True

    @staticmethod
    def _is_memory_storage(storage: Storage) -> bool:
        """Return whether the storage backend is the built-in memory storage.

        Args:
            storage: Storage backend to inspect.

        Returns:
            ``True`` when the storage is exactly ``MemoryStorage``. Subclasses
            are treated as non-memory backends so fallback logic can still be
            exercised in tests and custom implementations.

        Raises:
            None.
        """
        return type(storage) is MemoryStorage

    def _is_available(self, storage: Storage) -> bool:
        """Return whether the storage backend is healthy enough to use.

        Args:
            storage: Storage backend whose health should be checked.

        Returns:
            ``True`` when ``storage.check()`` succeeds and reports healthy,
            otherwise ``False``.

        Raises:
            None. Known storage connectivity errors are converted into
            ``False`` so the controller can trigger fallback behavior.
        """
        try:
            return storage.check()
        except STORAGE_BACKEND_EXCEPTIONS:
            return False

    def _switch_to_fallback_storage(
        self,
        reason: str,
        error: BaseException | None = None,
    ) -> None:
        """Activate in-memory fallback storage and schedule recovery probing.

        Args:
            reason: Human-readable description of why the fallback is needed.
            error: Original storage exception, if one triggered the switch.

        Returns:
            None.

        Raises:
            None.
        """
        if self._fallback_storage is None:
            self._fallback_storage = MemoryStorage()
        if self._fallback_limiter is None:
            self._fallback_limiter = FixedWindowRateLimiter(self._fallback_storage)
        self._using_fallback_storage = True
        self._current_recovery_backoff_seconds = self._recovery_backoff_seconds
        probe_delay = self._schedule_next_recovery_probe()
        if error is None:
            _STORAGE_LOGGER.warning(
                "%s. %s; first recovery probe in %.2f seconds.",
                reason,
                IN_MEMORY_FALLBACK_LOG_MESSAGE,
                probe_delay,
            )
            return
        _STORAGE_LOGGER.warning(
            "%s (%s: %s). %s; first recovery probe in %.2f seconds.",
            reason,
            error.__class__.__name__,
            error,
            IN_MEMORY_FALLBACK_LOG_MESSAGE,
            probe_delay,
        )

    def _schedule_next_recovery_probe(self) -> float:
        """Schedule the next primary storage recovery probe.

        Returns:
            The delay, in seconds, until the next probe.

        Raises:
            None.
        """
        probe_delay = self._current_recovery_backoff_seconds
        self._next_recovery_probe_at = time.monotonic() + probe_delay
        self._current_recovery_backoff_seconds = min(
            max(
                self._recovery_backoff_seconds,
                self._current_recovery_backoff_seconds * 2,
            ),
            self._max_recovery_backoff_seconds,
        )
        return probe_delay

    def _restore_primary_storage(self) -> None:
        """Restore the primary storage after a successful health probe.

        Returns:
            None.

        Raises:
            None.
        """
        self._using_fallback_storage = False
        self._current_recovery_backoff_seconds = self._recovery_backoff_seconds
        self._next_recovery_probe_at = 0.0
        _STORAGE_LOGGER.info(PRIMARY_STORAGE_RECOVERED_LOG_MESSAGE)

    def _restore_primary_storage_if_recovery_probe_is_due(self) -> None:
        """Restore primary storage when the scheduled recovery probe is due.

        Returns:
            None.

        Raises:
            None. Failed probes keep the controller on fallback storage and
            schedule the next probe using exponential backoff.
        """
        if (
            not self._using_fallback_storage
            or self._is_memory_storage(self._primary_storage)
            or time.monotonic() < self._next_recovery_probe_at
        ):
            return
        if self._is_available(self._primary_storage):
            self._restore_primary_storage()
            return
        probe_delay = self._schedule_next_recovery_probe()
        _STORAGE_LOGGER.warning(
            "%s %.2f seconds.",
            PRIMARY_STORAGE_STILL_UNAVAILABLE_LOG_MESSAGE,
            probe_delay,
        )
