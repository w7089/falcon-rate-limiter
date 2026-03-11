from functools import wraps

from dateutil.relativedelta import relativedelta
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
import asyncio
import falcon

from limiter.utils import _create_rate_limit_item


class FalconRateLimiter:
    def __init__(self, storage=None):
        if storage is None:
            storage = MemoryStorage()
        self._storage = storage
        self._limiter = FixedWindowRateLimiter(self._storage)

    def rate_limit(self, requests: int, per: relativedelta):
        # TODO create custom delta which will enforce that limits will be only per second, minute, hour, day, week, month, year
        def decorator(func):
            rate_limit_item = _create_rate_limit_item(requests, per)

            @wraps(func)
            def sync_wrapper(*args, **kwargs) -> None:
                if len(args) != 3:
                    raise ValueError("Expected 3 arguments: self, req, resp")
                resp = args[2]
                if not self._limiter.hit(rate_limit_item, func.__qualname__):
                    resp.status = falcon.HTTP_429
                    resp.text = "Rate limit exceeded"
                    return
                func(*args, **kwargs)

            if asyncio.iscoroutinefunction(func):
                pass
            else:
                return sync_wrapper

        return decorator

