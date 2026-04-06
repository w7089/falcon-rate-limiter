import inspect
from functools import wraps
from typing import Any, Callable

import falcon
from dateutil.relativedelta import relativedelta
from limits.storage import Storage

from limiter._helpers import (
    RateLimitDefinition,
    _check_rate_limit,
    _check_rate_limit_async,
    _get_request_response,
    _is_rate_limit_exempt,
    _mark_rate_limited,
    _mark_rate_limit_exempt,
)
from limiter.constants import DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
from limiter._storage import STORAGE_BACKEND_EXCEPTIONS, StorageController
from limiter.utils import (
    _create_rate_limit_item,
    _get_remote_address,
)


class FalconRateLimiter:
    """Main rate limiter for Falcon applications.

    Provides decorator-based rate limiting for responders and resource classes,
    with optional middleware integration for default limits on undecorated routes.

    Args:
        storage: Backend storage for rate limit counters. Defaults to in-memory.
        storage_uri: Storage URI resolved by ``limits`` (for example
            ``"memory://"`` or ``"redis://localhost:6379/0"``).
        key_func: Default function to extract client identifiers from requests.
        default_requests: Default limit count for middleware (requires default_per).
        default_per: Default time window for middleware (requires default_requests).
        headers_enabled: Whether to add X-RateLimit-* headers to responses.
        limit_undecorated_routes: Whether middleware should limit undecorated routes.
        recovery_backoff_seconds: Initial delay before probing failed primary
            storage for recovery.
        max_recovery_backoff_seconds: Maximum delay between recovery probes.
    """

    def __init__(
        self,
        storage: Storage | None = None,
        storage_uri: str | None = None,
        key_func: Callable[[falcon.Request], str] | None = None,
        default_requests: int | None = None,
        default_per: relativedelta | None = None,
        headers_enabled: bool = True,
        limit_undecorated_routes: bool = True,
        recovery_backoff_seconds: float = 1.0,
        max_recovery_backoff_seconds: float = 60.0,
    ) -> None:
        self._storage_controller = StorageController(
            storage=storage,
            storage_uri=storage_uri,
            recovery_backoff_seconds=recovery_backoff_seconds,
            max_recovery_backoff_seconds=max_recovery_backoff_seconds,
        )
        self._key_func = key_func
        self._default_limit = self._create_default_limit(default_requests, default_per)
        self._headers_enabled = headers_enabled
        self._limit_undecorated_routes = limit_undecorated_routes

    def _resolve_key_func(
        self, override: Callable[[falcon.Request], str] | None
    ) -> Callable[[falcon.Request], str]:
        """Resolve the key function to use for a rate limit.

        Priority order:
            1. Per-decorator override (if provided)
            2. Global key_func from __init__ (if provided)
            3. Default: extract client IP via ``_get_remote_address``

        Args:
            override: Key function passed to ``@rate_limit()``, or ``None``.

        Returns:
            The resolved key function.
        """
        if override is not None:
            return override
        if self._key_func is not None:
            return self._key_func
        return _get_remote_address

    @property
    def limit_undecorated_routes(self) -> bool:
        """Whether middleware should apply limits to undecorated routes."""
        return self._limit_undecorated_routes

    @property
    def default_limit(self) -> RateLimitDefinition | None:
        """The default limit used by middleware, or ``None`` if not configured."""
        return self._default_limit

    def _create_default_limit(
        self,
        default_requests: int | None,
        default_per: relativedelta | None,
    ) -> RateLimitDefinition | None:
        """Create the default limit definition for middleware.

        Args:
            default_requests: Maximum requests allowed in the window.
            default_per: Time window duration.

        Returns:
            A ``RateLimitDefinition`` if both arguments are provided,
            otherwise ``None``.

        Raises:
            ValueError: When only one of the two arguments is provided.
        """
        if default_requests is None and default_per is None:
            return None
        if default_requests is None or default_per is None:
            raise ValueError(
                "default_requests and default_per must be provided together"
            )
        return RateLimitDefinition(
            requests=default_requests,
            rate_limit_item=_create_rate_limit_item(default_requests, default_per),
            key_func=self._resolve_key_func(None),
            rejection_message=DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE,
        )

    def create_limit(
        self,
        requests: int,
        per: relativedelta,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
    ) -> RateLimitDefinition:
        """Create a reusable rate limit definition.

        Args:
            requests: Maximum requests allowed in the time window.
            per: Time window duration (e.g., ``relativedelta(minutes=1)``).
            key_func: Optional override for the client key extraction function.
            error_message: Custom message for HTTP 429 responses.

        Returns:
            A ``RateLimitDefinition`` that can be passed to ``enforce_limit``.
        """
        return RateLimitDefinition(
            requests=requests,
            rate_limit_item=_create_rate_limit_item(requests, per),
            key_func=self._resolve_key_func(key_func),
            rejection_message=error_message or DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE,
        )

    def enforce_limit(
        self,
        limit: RateLimitDefinition,
        scope: str,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        """Enforce a rate limit synchronously.

        Args:
            limit: The limit definition to enforce.
            scope: Identifier for the endpoint (usually ``__qualname__``).
            req: The incoming Falcon request.
            resp: The Falcon response (may have headers added).

        Raises:
            falcon.HTTPTooManyRequests: When the rate limit is exceeded.
        """
        limiter = self._storage_controller.limiter_for_enforcement()
        try:
            _check_rate_limit(
                limiter,
                limit,
                self._headers_enabled,
                scope,
                req,
                resp,
            )
        except STORAGE_BACKEND_EXCEPTIONS as exc:
            if not self._storage_controller.activate_fallback_storage_for_error(exc):
                raise
            _check_rate_limit(
                self._storage_controller.current_limiter,
                limit,
                self._headers_enabled,
                scope,
                req,
                resp,
            )

    def enforce_limits(
        self,
        limits: tuple[RateLimitDefinition, ...],
        scope: str,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        """Enforce multiple rate limits synchronously.

        Args:
            limits: Tuple of limit definitions to enforce in order.
            scope: Identifier for the endpoint.
            req: The incoming Falcon request.
            resp: The Falcon response.

        Raises:
            falcon.HTTPTooManyRequests: When any limit is exceeded.
        """
        for limit in limits:
            self.enforce_limit(limit, scope, req, resp)

    async def enforce_limit_async(
        self,
        limit: RateLimitDefinition,
        scope: str,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        """Enforce a rate limit asynchronously.

        Blocking storage calls are offloaded to a thread pool to avoid
        blocking the event loop in ASGI applications.

        Args:
            limit: The limit definition to enforce.
            scope: Identifier for the endpoint.
            req: The incoming Falcon request.
            resp: The Falcon response.

        Raises:
            falcon.HTTPTooManyRequests: When the rate limit is exceeded.
        """
        limiter = self._storage_controller.limiter_for_enforcement()
        try:
            await _check_rate_limit_async(
                limiter,
                limit,
                self._headers_enabled,
                scope,
                req,
                resp,
            )
        except STORAGE_BACKEND_EXCEPTIONS as exc:
            if not self._storage_controller.activate_fallback_storage_for_error(exc):
                raise
            await _check_rate_limit_async(
                self._storage_controller.current_limiter,
                limit,
                self._headers_enabled,
                scope,
                req,
                resp,
            )

    async def enforce_limits_async(
        self,
        limits: tuple[RateLimitDefinition, ...],
        scope: str,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        """Enforce multiple rate limits asynchronously.

        Args:
            limits: Tuple of limit definitions to enforce in order.
            scope: Identifier for the endpoint.
            req: The incoming Falcon request.
            resp: The Falcon response.

        Raises:
            falcon.HTTPTooManyRequests: When any limit is exceeded.
        """
        for limit in limits:
            await self.enforce_limit_async(limit, scope, req, resp)

    @staticmethod
    def _is_exempt_call(target: Any, wrapper: Any, args: tuple[Any, ...]) -> bool:
        """Return whether a decorated responder call should bypass limiting.

        This helper checks both the original callable and the generated wrapper
        so ``@limiter.exempt`` works regardless of decorator order. It also
        checks the bound resource instance and its class to support exemptions
        applied at the resource level.

        Args:
            target: Original responder or callable passed to ``rate_limit``.
            wrapper: Wrapper created by ``rate_limit`` for the target.
            args: Positional arguments received by the wrapper. When present,
                the first argument is expected to be the resource instance.

        Returns:
            ``True`` when the call should skip rate-limit enforcement,
            otherwise ``False``.

        Raises:
            None.
        """
        # Check both callable layers because ``@limiter.exempt`` may wrap the
        # original responder or the returned rate-limit wrapper.
        if _is_rate_limit_exempt(target) or _is_rate_limit_exempt(wrapper):
            return True
        if not args:
            return False
        # args[0] is the resource instance (self) because this wrapper decorates
        # a method. Falcon calls resource.on_get(req, resp), so inside the wrapper
        # args = (resource_instance, req, resp, ...).
        resource = args[0]
        # Check both the instance and its class to support:
        # - limiter.exempt(some_instance)  -> instance-level exemption
        # - @limiter.exempt on class       -> class-level exemption
        resource_type = type(resource)
        return _is_rate_limit_exempt(resource) or _is_rate_limit_exempt(resource_type)

    def exempt(self, target: Any) -> Any:
        """Mark a responder, resource instance, or resource class as exempt.

        The returned target is unchanged apart from an internal marker used by
        the decorator wrappers and middleware to skip rate-limit checks.

        Args:
            target: Callable, resource instance, or resource class to exempt
                from explicit and default limits.

        Returns:
            The same target object, allowing use as a decorator.

        Raises:
            AttributeError: Raised when the target does not allow attribute
                assignment for the exemption marker.
        """
        _mark_rate_limit_exempt(target)
        return target

    def rate_limit(
        self,
        requests: int,
        per: relativedelta,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
    ) -> Callable[[Any], Any]:
        """Decorator to apply a rate limit to a responder or resource class.

        When applied to a class, all methods starting with ``on_`` are wrapped.
        The decorator detects async responders and uses thread-safe async
        enforcement to avoid blocking the event loop.

        Args:
            requests: Maximum requests allowed in the time window.
            per: Time window duration (e.g., ``relativedelta(seconds=10)``).
            key_func: Optional override for client key extraction.
            error_message: Custom message for HTTP 429 responses.

        Returns:
            A decorator that wraps the target with rate limit enforcement.

        Example::

            @limiter.rate_limit(requests=5, per=relativedelta(minutes=1))
            def on_get(self, req, resp):
                ...
        """
        resolved_limit = self.create_limit(
            requests=requests,
            per=per,
            key_func=key_func,
            error_message=error_message,
        )

        def decorator(target: Any) -> Any:
            # When decorating a class, wrap all on_* responder methods
            if inspect.isclass(target):
                for name, value in vars(target).items():
                    if name.startswith("on_") and callable(value):
                        setattr(target, name, decorator(value))
                _mark_rate_limited(target)
                return target

            @wraps(target)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # args = (self/resource, req, resp, ...) for bound methods
                if self._is_exempt_call(target, sync_wrapper, args):
                    return target(*args, **kwargs)
                req, resp = _get_request_response(args)
                self.enforce_limit(resolved_limit, target.__qualname__, req, resp)
                return target(*args, **kwargs)

            @wraps(target)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # args = (self/resource, req, resp, ...) for bound methods
                if self._is_exempt_call(target, async_wrapper, args):
                    return await target(*args, **kwargs)
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
