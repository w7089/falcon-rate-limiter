import asyncio
import inspect
from functools import wraps
from typing import Callable

from dateutil.relativedelta import relativedelta
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
import falcon

from limiter.utils import _create_rate_limit_item




class FalconRateLimiter:
    def __init__(self, storage=None, key_func: Callable[[falcon.Request], str] | None = None):
        if storage is None:
            storage = MemoryStorage()
        self._storage = storage
        self._limiter = FixedWindowRateLimiter(self._storage)
        self._key_func = key_func

    def _resolve_key_func(self, override: Callable[[falcon.Request], str] | None) -> Callable[[falcon.Request], str]:
        if override is not None:
            return override
        if self._key_func is not None:
            return self._key_func
        return lambda req: req.remote_addr or "global"

    def rate_limit(self, requests: int, per: relativedelta, key_func: Callable[[falcon.Request], str] | None = None):
        # TODO create custom delta which will enforce that limits will be only per second, minute, hour, day, week, month, year
        client_key_func = self._resolve_key_func(key_func)

        def decorator(target):
            if inspect.isclass(target):
                for name, value in vars(target).items():
                    if name.startswith("on_") and callable(value):
                        setattr(target, name, decorator(value))
                return target

            rate_limit_item = _create_rate_limit_item(requests, per)

            def _get_request_response(args):
                # Falcon resource methods: self, req, resp, ...
                if len(args) >= 3:
                    return args[1], args[2]
                raise TypeError("Wrapped Falcon responder is missing request/response arguments (expected self, req, resp)")

            def _build_key(req):
                client_id = client_key_func(req)
                return f"{target.__qualname__}:{client_id}"

            @wraps(target)
            def sync_wrapper(*args, **kwargs) -> object | None:
                req, resp = _get_request_response(args)
                key = _build_key(req)
                if not self._limiter.hit(rate_limit_item, key):
                    resp.status = falcon.HTTP_429
                    resp.text = "Rate limit exceeded"
                    return None
                return target(*args, **kwargs)

            @wraps(target)
            async def async_wrapper(*args, **kwargs) -> object | None:
                req, resp = _get_request_response(args)
                key = _build_key(req)
                is_allowed = await asyncio.to_thread(
                    lambda: self._limiter.hit(rate_limit_item, key)
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
