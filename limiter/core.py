import asyncio
import inspect
from functools import wraps

from dateutil.relativedelta import relativedelta
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
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
        def decorator(target):
            if inspect.isclass(target):
                for name, value in vars(target).items():
                    if name.startswith("on_") and callable(value):
                        setattr(target, name, decorator(value))
                return target

            rate_limit_item = _create_rate_limit_item(requests, per)

            def _get_response(args):
                # Falcon resource methods: self, req, resp, ...
                if len(args) >= 3:
                    return args[2]
                raise TypeError("Wrapped Falcon responder is missing response argument (expected self, req, resp)")

            @wraps(target)
            def sync_wrapper(*args, **kwargs) -> object | None:
                resp = _get_response(args)
                if not self._limiter.hit(rate_limit_item, target.__qualname__):
                    resp.status = falcon.HTTP_429
                    resp.text = "Rate limit exceeded"
                    return None
                return target(*args, **kwargs)

            @wraps(target)
            async def async_wrapper(*args, **kwargs) -> object | None:
                resp = _get_response(args)
                is_allowed = await asyncio.to_thread(
                    self._limiter.hit,
                    rate_limit_item,
                    target.__qualname__,
                )
                if not is_allowed:
                    resp.status = falcon.HTTP_429
                    resp.text = "Rate limit exceeded"
                    return None
                return await target(*args, **kwargs)

            if inspect.iscoroutinefunction(target):
                return async_wrapper
            return sync_wrapper

        return decorator

