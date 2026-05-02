import inspect
from typing import TYPE_CHECKING, Any, Callable

from dateutil.relativedelta import relativedelta
import falcon

from limiter._helpers import _is_rate_limit_exempt, _is_rate_limited

if TYPE_CHECKING:
    from limiter.core import FalconRateLimiter


class FalconRateLimitMiddleware:
    """Falcon middleware that applies default rate limits to undecorated routes.

    This middleware integrates with ``FalconRateLimiter`` to automatically
    enforce limits on responders that do not have explicit ``@rate_limit``
    decorators. It skips routes that are already decorated or marked exempt.

    Args:
        limiter: The ``FalconRateLimiter`` instance to use for enforcement.
        requests: Explicit limit count (requires ``per``). If omitted, uses
            the limiter's default limit.
        per: Explicit time window (requires ``requests``).
        key_func: Optional override for client key extraction.
        error_message: Custom message for HTTP 429 responses.
        per_method: Whether to include the request method in the rate-limit key.
        exempt_when: Optional predicate that skips this limit when it returns ``True``.

    Raises:
        ValueError: When only one of ``requests`` or ``per`` is provided.
    """

    def __init__(
        self,
        limiter: "FalconRateLimiter",
        *,
        requests: int | None = None,
        per: relativedelta | None = None,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
        per_method: bool = False,
        exempt_when: Callable[[falcon.Request], bool] | None = None,
        cost: int | Callable[[falcon.Request], int] = 1,
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
                per_method=per_method,
                exempt_when=exempt_when,
                cost=cost,
            )
        else:
            raise ValueError("requests and per must be provided together")

    @staticmethod
    def _is_decorated_resource_or_responder(resource: Any, responder: Any) -> bool:
        """Return whether the resource or responder has explicit rate limits.

        This is used to skip middleware enforcement for routes that already
        have ``@rate_limit`` decorators applied.

        Args:
            resource: Falcon resource instance or class.
            responder: The resolved responder method (e.g., ``on_get``).

        Returns:
            ``True`` if either has the rate-limited marker, otherwise ``False``.
        """
        resource_type = resource if inspect.isclass(resource) else type(resource)
        return _is_rate_limited(responder) or _is_rate_limited(resource_type)

    @staticmethod
    def _is_exempt_resource_or_responder(resource: Any, responder: Any) -> bool:
        """Return whether middleware should skip a resource or responder.

        Checks the responder, resource instance, and resource class for the
        exemption marker. This ensures ``@limiter.exempt`` works whether
        applied to the method, an instance, or the class.

        Args:
            resource: Falcon resource instance or class currently being
                processed.
            responder: Responder resolved for the incoming HTTP method.

        Returns:
            ``True`` when the responder, resource instance, or resource class
            has been marked with ``@limiter.exempt``; otherwise ``False``.
        """
        resource_type = resource if inspect.isclass(resource) else type(resource)
        # Check all three levels:
        # - responder: method-level @limiter.exempt
        # - resource: instance-level limiter.exempt(instance)
        # - resource_type: class-level @limiter.exempt on the class
        return (
            _is_rate_limit_exempt(responder)
            or _is_rate_limit_exempt(resource)
            or _is_rate_limit_exempt(resource_type)
        )

    @staticmethod
    def _scope_for(responder: Any) -> str:
        """Get the scope identifier for a responder.

        Uses ``__qualname__`` (e.g., ``Resource.on_get``) for per-endpoint
        tracking, falling back to ``__name__`` or ``"global"``.

        Args:
            responder: The resolved responder method.

        Returns:
            A string identifier for rate limit key scoping.
        """
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
        """Falcon middleware hook for WSGI request processing.

        Enforces rate limits on undecorated, non-exempt routes. Skips
        processing if the responder is missing, decorated, exempt, or if
        ``limit_undecorated_routes`` is disabled.

        Args:
            req: The incoming Falcon request.
            resp: The Falcon response.
            resource: The matched Falcon resource instance.
            params: URI template parameters (unused).

        Raises:
            falcon.HTTPTooManyRequests: When the rate limit is exceeded.
        """
        del params  # Unused but required by Falcon's middleware signature
        # Resolve the responder for this HTTP method (e.g., on_get, on_post)
        responder = getattr(resource, f"on_{req.method.lower()}", None)
        if (
            responder is None
            or not self._limiter.limit_undecorated_routes
            or self._resolved_limit is None
        ):
            return
        if self._is_exempt_resource_or_responder(resource, responder):
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
        """Falcon middleware hook for ASGI request processing.

        Async version of ``process_resource``. Blocking storage calls are
        offloaded to a thread pool to avoid blocking the event loop.

        Args:
            req: The incoming Falcon request.
            resp: The Falcon response.
            resource: The matched Falcon resource instance.
            params: URI template parameters (unused).

        Raises:
            falcon.HTTPTooManyRequests: When the rate limit is exceeded.
        """
        del params  # Unused but required by Falcon's middleware signature
        # Resolve the responder for this HTTP method (e.g., on_get, on_post)
        responder = getattr(resource, f"on_{req.method.lower()}", None)
        if (
            responder is None
            or not self._limiter.limit_undecorated_routes
            or self._resolved_limit is None
        ):
            return
        if self._is_exempt_resource_or_responder(resource, responder):
            return
        if self._is_decorated_resource_or_responder(resource, responder):
            return
        await self._limiter.enforce_limit_async(
            self._resolved_limit, self._scope_for(responder), req, resp
        )
