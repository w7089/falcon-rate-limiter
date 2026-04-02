import inspect
from typing import TYPE_CHECKING, Any, Callable

from dateutil.relativedelta import relativedelta
import falcon

from limiter._helpers import _is_rate_limited

if TYPE_CHECKING:
    from limiter.core import FalconRateLimiter


class FalconRateLimitMiddleware:
    def __init__(
        self,
        limiter: "FalconRateLimiter",
        requests: int | None = None,
        per: relativedelta | None = None,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
    ) -> None:
        self._limiter = limiter
        if requests is None and per is None:
            self._resolved_limit = limiter.default_limit
        elif requests is not None and per is not None:
            self._resolved_limit = limiter.create_limit(
                requests=requests,
                per=per,
                key_func=key_func,
                error_message=error_message,
            )
        else:
            raise ValueError("requests and per must be provided together")

    @staticmethod
    def _is_decorated_resource_or_responder(resource: Any, responder: Any) -> bool:
        resource_type = resource if inspect.isclass(resource) else type(resource)
        return _is_rate_limited(responder) or _is_rate_limited(resource_type)

    @staticmethod
    def _scope_for(responder: Any) -> str:
        return getattr(
            responder, "__qualname__", getattr(responder, "__name__", "global")
        )

    def process_resource(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        resource: object,
        params: dict[str, Any],
    ) -> None:
        del params
        responder = getattr(resource, f"on_{req.method.lower()}", None)
        if (
            responder is None
            or not self._limiter.limit_undecorated_routes
            or self._resolved_limit is None
        ):
            return
        if self._is_decorated_resource_or_responder(resource, responder):
            return
        self._limiter.enforce_limit(
            self._resolved_limit, self._scope_for(responder), req, resp
        )

    async def process_resource_async(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        resource: object,
        params: dict[str, Any],
    ) -> None:
        del params
        responder = getattr(resource, f"on_{req.method.lower()}", None)
        if (
            responder is None
            or not self._limiter.limit_undecorated_routes
            or self._resolved_limit is None
        ):
            return
        if self._is_decorated_resource_or_responder(resource, responder):
            return
        await self._limiter.enforce_limit_async(
            self._resolved_limit, self._scope_for(responder), req, resp
        )
