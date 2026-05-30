from limits.storage import MemoryStorage
from limits.strategies import (
    FixedWindowRateLimiter,
    MovingWindowRateLimiter,
    SlidingWindowCounterRateLimiter,
)
import pytest

from limiter._storage import StorageController
from limiter.constants import (
    FIXED_WINDOW_STRATEGY,
    INVALID_RATE_LIMIT_STRATEGY_ERROR_MESSAGE,
    MOVING_WINDOW_STRATEGY,
    SLIDING_WINDOW_COUNTER_STRATEGY,
)
from limiter.core import FalconRateLimiter
from tests.test_storage import FlakyMemoryStorage


@pytest.mark.parametrize(
    ("strategy", "expected_type"),
    [
        pytest.param(
            FIXED_WINDOW_STRATEGY,
            FixedWindowRateLimiter,
            id="fixed-window",
        ),
        pytest.param(
            MOVING_WINDOW_STRATEGY,
            MovingWindowRateLimiter,
            id="moving-window",
        ),
        pytest.param(
            SLIDING_WINDOW_COUNTER_STRATEGY,
            SlidingWindowCounterRateLimiter,
            id="sliding-window-counter",
        ),
    ],
)
def test_storage_controller_uses_configured_strategy(
    strategy: str,
    expected_type: type[
        FixedWindowRateLimiter
        | MovingWindowRateLimiter
        | SlidingWindowCounterRateLimiter
    ],
) -> None:
    controller = StorageController(storage=MemoryStorage(), strategy=strategy)

    assert isinstance(controller.current_limiter, expected_type)


def test_storage_controller_uses_configured_strategy_for_fallback() -> None:
    storage = FlakyMemoryStorage()
    controller = StorageController(
        storage=storage,
        strategy=MOVING_WINDOW_STRATEGY,
        recovery_backoff_seconds=0.0,
        max_recovery_backoff_seconds=0.0,
    )

    activated = controller.activate_fallback_storage_for_error(RuntimeError("boom"))

    assert activated is True
    assert isinstance(controller.current_limiter, MovingWindowRateLimiter)


def test_storage_controller_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError, match=INVALID_RATE_LIMIT_STRATEGY_ERROR_MESSAGE):
        StorageController(storage=MemoryStorage(), strategy="not-a-strategy")


def test_limiter_constructor_passes_strategy_to_storage_controller() -> None:
    limiter = FalconRateLimiter(strategy=SLIDING_WINDOW_COUNTER_STRATEGY)

    assert isinstance(
        limiter._storage_controller.current_limiter,
        SlidingWindowCounterRateLimiter,
    )
