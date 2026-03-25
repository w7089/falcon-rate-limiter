import inspect
from functools import wraps
from typing import Any, Callable

import falcon
from dateutil.relativedelta import relativedelta
from limits.storage import MemoryStorage, Storage
from limits.strategies import FixedWindowRateLimiter

from limiter._helpers import (
    RateLimitDefinition,
    _check_rate_limit,
    _check_rate_limit_async,
    _get_request_response,
    _mark_rate_limited,
)
from limiter.utils import _create_rate_limit_item, _get_remote_address


class FalconRateLimiter:
    def __init__(
        self,
        storage: Storage | None = None,
        key_func: Callable[[falcon.Request], str] | None = None,
        headers_enabled: bool = True,
        limit_undecorated_routes: bool = True,
    ) -> None:
        if storage is None:
            storage = MemoryStorage()
        self._storage = storage
        self._limiter = FixedWindowRateLimiter(self._storage)
        self._key_func = key_func
        self._headers_enabled = headers_enabled
        self._limit_undecorated_routes = limit_undecorated_routes

    def _resolve_key_func(
        self, override: Callable[[falcon.Request], str] | None
    ) -> Callable[[falcon.Request], str]:
        if override is not None:
            return override
        if self._key_func is not None:
            return self._key_func
        return _get_remote_address

    @property
    def limit_undecorated_routes(self) -> bool:
        return self._limit_undecorated_routes

    def create_limit(
        self,
        requests: int,
        per: relativedelta,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
    ) -> RateLimitDefinition:
        return RateLimitDefinition(
            requests=requests,
            rate_limit_item=_create_rate_limit_item(requests, per),
            key_func=self._resolve_key_func(key_func),
            rejection_message=error_message or "Rate limit exceeded",
        )

    def enforce_limit(
        self,
        limit: RateLimitDefinition,
        scope: str,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        _check_rate_limit(
            self._limiter,
            limit,
            self._headers_enabled,
            scope,
            req,
            resp,
        )

    async def enforce_limit_async(
        self,
        limit: RateLimitDefinition,
        scope: str,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        await _check_rate_limit_async(
            self._limiter,
            limit,
            self._headers_enabled,
            scope,
            req,
            resp,
        )

    def rate_limit(
        self,
        requests: int,
        per: relativedelta,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
    ) -> Callable[[Any], Any]:
        resolved_limit = self.create_limit(
            requests=requests,
            per=per,
            key_func=key_func,
            error_message=error_message,
        )

        def decorator(target: Any) -> Any:
            if inspect.isclass(target):
                for name, value in vars(target).items():
                    if name.startswith("on_") and callable(value):
                        setattr(target, name, decorator(value))
                _mark_rate_limited(target)
                return target

            @wraps(target)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                req, resp = _get_request_response(args)
                self.enforce_limit(resolved_limit, target.__qualname__, req, resp)
                return target(*args, **kwargs)

            @wraps(target)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                req, resp = _get_request_response(args)
                await self.enforce_limit_async(
                    resolved_limit, target.__qualname__, req, resp
                )
                return await target(*args, **kwargs)

            _mark_rate_limited(target)
            if inspect.iscoroutinefunction(target):
                _mark_rate_limited(async_wrapper)
                return async_wrapper
            _mark_rate_limited(sync_wrapper)
            return sync_wrapper

        return decorator
