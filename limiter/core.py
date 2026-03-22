import asyncio
import inspect
import time
from functools import wraps
from typing import Callable, Any, Sequence, cast

from dateutil.relativedelta import relativedelta
from limits.storage import Storage, MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from limits.util import WindowStats
import falcon

from limiter.utils import _create_rate_limit_item


def _get_remote_address(req: falcon.Request) -> str:
    access_route = cast(Sequence[str] | None, getattr(req, "access_route", None))
    if access_route:
        return access_route[0]
    remote_addr = req.remote_addr
    return remote_addr if remote_addr is not None else "global"


class FalconRateLimiter:
    def __init__(
        self,
        storage: Storage | None = None,
        key_func: Callable[[falcon.Request], str] | None = None,
        headers_enabled: bool = True,
    ) -> None:
        if storage is None:
            storage = MemoryStorage()
        self._storage = storage
        self._limiter = FixedWindowRateLimiter(self._storage)
        self._key_func = key_func
        self._headers_enabled = headers_enabled

    def _resolve_key_func(
        self, override: Callable[[falcon.Request], str] | None
    ) -> Callable[[falcon.Request], str]:
        if override is not None:
            return override
        if self._key_func is not None:
            return self._key_func
        return _get_remote_address

    def rate_limit(
        self,
        requests: int,
        per: relativedelta,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
    ) -> Callable[[Any], Any]:
        # TODO create custom delta which will enforce that limits will be only per second, minute, hour, day, week, month, year
        client_key_func = self._resolve_key_func(key_func)
        rejection_message = error_message or "Rate limit exceeded"

        def decorator(target: Any) -> Any:
            if inspect.isclass(target):
                for name, value in vars(target).items():
                    if name.startswith("on_") and callable(value):
                        setattr(target, name, decorator(value))
                return target

            rate_limit_item = _create_rate_limit_item(requests, per)

            def _get_request_response(
                args: tuple[Any, ...],
            ) -> tuple[falcon.Request, falcon.Response]:
                # Falcon resource methods: self, req, resp, ...
                if len(args) >= 3:
                    return cast(falcon.Request, args[1]), cast(falcon.Response, args[2])
                raise TypeError(
                    "Wrapped Falcon responder is missing request/response arguments (expected self, req, resp)"
                )

            def _build_key(req: falcon.Request) -> str:
                client_id = client_key_func(req)
                return f"{target.__qualname__}:{client_id}"

            def _set_headers(resp: falcon.Response, stats: WindowStats) -> None:
                reset_time = int(stats.reset_time)
                resp.set_header("X-RateLimit-Limit", str(requests))
                resp.set_header("X-RateLimit-Remaining", str(stats.remaining))
                resp.set_header("X-RateLimit-Reset", str(reset_time))

            def _retry_after_seconds(stats: WindowStats | None) -> int | None:
                if stats is None:
                    return None
                return max(0, int(stats.reset_time - time.time()))

            @wraps(target)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                req, resp = _get_request_response(args)
                key = _build_key(req)
                allowed = self._limiter.hit(rate_limit_item, key)
                stats: WindowStats | None = None
                if self._headers_enabled or not allowed:
                    stats = self._limiter.get_window_stats(rate_limit_item, key)
                if self._headers_enabled and stats is not None:
                    _set_headers(resp, stats)
                if not allowed:
                    retry_after = _retry_after_seconds(stats)
                    raise falcon.HTTPTooManyRequests(
                        description=rejection_message,
                        retry_after=retry_after,
                    )
                return target(*args, **kwargs)

            @wraps(target)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                req, resp = _get_request_response(args)
                key = _build_key(req)

                def _hit_and_stats() -> tuple[bool, WindowStats | None]:
                    hit_allowed = self._limiter.hit(rate_limit_item, key)
                    hit_stats = (
                        self._limiter.get_window_stats(rate_limit_item, key)
                        if self._headers_enabled or not hit_allowed
                        else None
                    )
                    return hit_allowed, hit_stats

                allowed, stats = await asyncio.to_thread(_hit_and_stats)
                if self._headers_enabled and stats is not None:
                    _set_headers(resp, stats)
                if not allowed:
                    retry_after = _retry_after_seconds(
                        stats
                        if stats is not None
                        else self._limiter.get_window_stats(rate_limit_item, key)
                    )
                    raise falcon.HTTPTooManyRequests(
                        description=rejection_message,
                        retry_after=retry_after,
                    )
                return await target(*args, **kwargs)

            if inspect.iscoroutinefunction(target):
                return async_wrapper
            return sync_wrapper

        return decorator
