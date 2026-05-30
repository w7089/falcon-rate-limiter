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
    MOVING_WINDOW_STRATEGY,
    SLIDING_WINDOW_COUNTER_STRATEGY,
)


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
