import inspect
import logging
from functools import wraps
from typing import Any, Callable

import falcon
from dateutil.relativedelta import relativedelta
from limits import parse
from limits.storage import Storage

from limiter._config import (
    get_optional_bool_env,
    get_optional_float_env,
    get_optional_string_env,
)
from limiter._helpers import (
    RateLimitDefinition,
    _check_rate_limit,
    _check_rate_limit_async,
    _get_request_response,
    _is_rate_limit_exempt,
    _mark_rate_limited,
    _mark_rate_limit_exempt,
)
from limiter.constants import (
    DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE,
    DEFAULT_STRATEGY,
    LOGGER_NAME,
    RATELIMIT_ENABLED_ENV,
    RATELIMIT_HEADERS_ENABLED_ENV,
    RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV,
    RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV,
    RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV,
    RATELIMIT_STORAGE_URL_ENV,
    RATELIMIT_STRATEGY_ENV,
    RATELIMIT_SWALLOW_ERRORS_ENV,
    SWALLOWED_RATE_LIMIT_ERROR_LOG_MESSAGE,
)
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
            ``None`` falls back to environment config and then the library default.
        limit_undecorated_routes: Whether middleware should limit undecorated
            routes. ``None`` falls back to environment config and then the
            library default.
        strategy: Rate-limiting strategy name. Supported values are
            ``"fixed-window"`` (default), ``"moving-window"``, and
            ``"sliding-window-counter"``. ``None`` falls back to the
            ``RATELIMIT_STRATEGY`` environment variable and then the library
            default.
        enabled: Whether rate limiting is active. ``None`` falls back to
            environment config and then the library default.
        swallow_errors: Whether request-time limiter errors should be logged and
            ignored instead of bubbling out. ``None`` falls back to environment
            config and then the library default.
        recovery_backoff_seconds: Initial delay before probing failed primary
            storage for recovery. ``None`` falls back to environment config and
            then the library default.
        max_recovery_backoff_seconds: Maximum delay between recovery probes.
            ``None`` falls back to environment config and then the library default.
    """

    def __init__(
        self,
        storage: Storage | None = None,
        storage_uri: str | None = None,
        key_func: Callable[[falcon.Request], str] | None = None,
        default_requests: int | None = None,
        default_per: relativedelta | None = None,
        headers_enabled: bool | None = None,
        limit_undecorated_routes: bool | None = None,
        strategy: str | None = None,
        enabled: bool | None = None,
        swallow_errors: bool | None = None,
        recovery_backoff_seconds: float | None = None,
        max_recovery_backoff_seconds: float | None = None,
    ) -> None:
        env_headers_enabled = (
            get_optional_bool_env(RATELIMIT_HEADERS_ENABLED_ENV)
            if headers_enabled is None
            else None
        )
        env_limit_undecorated_routes = (
            get_optional_bool_env(RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV)
            if limit_undecorated_routes is None
            else None
        )
        env_enabled = (
            get_optional_bool_env(RATELIMIT_ENABLED_ENV) if enabled is None else None
        )
        env_swallow_errors = (
            get_optional_bool_env(RATELIMIT_SWALLOW_ERRORS_ENV)
            if swallow_errors is None
            else None
        )
        env_recovery_backoff_seconds = (
            get_optional_float_env(RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV)
            if recovery_backoff_seconds is None
            else None
        )
        env_max_recovery_backoff_seconds = (
            get_optional_float_env(RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV)
            if max_recovery_backoff_seconds is None
            else None
        )
        resolved_storage_uri = storage_uri if storage is None else None
        if resolved_storage_uri is None and storage is None:
            resolved_storage_uri = get_optional_string_env(RATELIMIT_STORAGE_URL_ENV)

        resolved_strategy = (
            strategy
            if strategy is not None
            else get_optional_string_env(RATELIMIT_STRATEGY_ENV) or DEFAULT_STRATEGY
        )

        resolved_recovery_backoff_seconds = (
            recovery_backoff_seconds
            if recovery_backoff_seconds is not None
            else env_recovery_backoff_seconds
            if env_recovery_backoff_seconds is not None
            else 1.0
        )
        resolved_max_recovery_backoff_seconds = (
            max_recovery_backoff_seconds
            if max_recovery_backoff_seconds is not None
            else env_max_recovery_backoff_seconds
            if env_max_recovery_backoff_seconds is not None
            else 60.0
        )

        self._storage_controller = StorageController(
            storage=storage,
            storage_uri=resolved_storage_uri,
            strategy=resolved_strategy,
            recovery_backoff_seconds=resolved_recovery_backoff_seconds,
            max_recovery_backoff_seconds=resolved_max_recovery_backoff_seconds,
        )
        self._logger = logging.getLogger(LOGGER_NAME)
        self._key_func = key_func
        self._default_limit = self._create_default_limit(default_requests, default_per)
        self._headers_enabled = (
            headers_enabled
            if headers_enabled is not None
            else env_headers_enabled
            if env_headers_enabled is not None
            else True
        )
        self._limit_undecorated_routes = (
            limit_undecorated_routes
            if limit_undecorated_routes is not None
            else env_limit_undecorated_routes
            if env_limit_undecorated_routes is not None
            else True
        )
        self._enabled = (
            enabled
            if enabled is not None
            else env_enabled
            if env_enabled is not None
            else True
        )
        self._swallow_errors = (
            swallow_errors
            if swallow_errors is not None
            else env_swallow_errors
            if env_swallow_errors is not None
            else False
        )

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
    def enabled(self) -> bool:
        """Whether rate limiting is currently enabled."""
        return self._enabled

    @property
    def default_limit(self) -> RateLimitDefinition | None:
        """The default limit used by middleware, or ``None`` if not configured."""
        return self._default_limit

    def _swallow_enforcement_error(
        self,
        error: BaseException,
        scope: str,
    ) -> bool:
        """Log and swallow a request-time limiter error when configured.

        Args:
            error: The request-time limiter error that was raised.
            scope: The scope that was being enforced.

        Returns:
            ``True`` when the error was swallowed, otherwise ``False``.
        """

        if not self._swallow_errors:
            return False
        self._logger.exception(
            "%s scope=%s error=%s",
            SWALLOWED_RATE_LIMIT_ERROR_LOG_MESSAGE,
            scope,
            error.__class__.__name__,
        )
        return True

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
        exempt_when: Callable[[falcon.Request], bool] | None = None,
        cost: int | Callable[[falcon.Request], int] = 1,
        methods: list[str] | tuple[str, ...] | None = None,
        per_method: bool = False,
    ) -> RateLimitDefinition:
        """Create a reusable rate limit definition.

        Args:
            requests: Maximum requests allowed in the time window.
            per: Time window duration (e.g., ``relativedelta(minutes=1)``).
            key_func: Optional override for the client key extraction function.
            error_message: Custom message for HTTP 429 responses.
            exempt_when: Optional request predicate that skips rate limiting
                when it returns ``True``.
            cost: Either a static hit cost or a request-based callable that
                returns the hit cost for each request.
            methods: Optional HTTP methods that should trigger the limit.
            per_method: Whether requests that share the same responder should
                keep separate counters per HTTP method.

        Returns:
            A ``RateLimitDefinition`` that can be passed to ``enforce_limit``.

        Raises:
            ValueError: When ``methods`` is empty or a static ``cost`` is not a
                positive integer.
        """
        if isinstance(cost, int) and (isinstance(cost, bool) or cost <= 0):
            raise ValueError("cost must be a positive integer")
        return RateLimitDefinition(
            requests=requests,
            rate_limit_item=_create_rate_limit_item(requests, per),
            key_func=self._resolve_key_func(key_func),
            rejection_message=error_message or DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE,
            exempt_when=exempt_when,
            cost=cost,
            methods=self._normalize_methods(methods),
            per_method=per_method,
        )

    @staticmethod
    def _normalize_methods(
        methods: list[str] | tuple[str, ...] | None,
    ) -> frozenset[str] | None:
        """Normalize an optional method filter to uppercase method names.

        Args:
            methods: Optional iterable of HTTP methods such as ``["GET", "POST"]``.

        Returns:
            ``None`` when no filter is configured, otherwise a frozenset of
            uppercase method names.

        Raises:
            ValueError: When the list is empty or contains blank method names.
        """

        if methods is None:
            return None
        normalized_methods = frozenset(method.upper() for method in methods if method)
        if not normalized_methods:
            raise ValueError("methods must contain at least one HTTP method")
        return normalized_methods

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
        if not self._enabled:
            return
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
                if self._swallow_enforcement_error(exc, scope):
                    return
                raise
            try:
                _check_rate_limit(
                    self._storage_controller.current_limiter,
                    limit,
                    self._headers_enabled,
                    scope,
                    req,
                    resp,
                )
            except STORAGE_BACKEND_EXCEPTIONS as retry_exc:
                if self._swallow_enforcement_error(retry_exc, scope):
                    return
                raise
        except ValueError as exc:
            if self._swallow_enforcement_error(exc, scope):
                return
            raise

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
        if not self._enabled:
            return
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
        if not self._enabled:
            return
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
                if self._swallow_enforcement_error(exc, scope):
                    return
                raise
            try:
                await _check_rate_limit_async(
                    self._storage_controller.current_limiter,
                    limit,
                    self._headers_enabled,
                    scope,
                    req,
                    resp,
                )
            except STORAGE_BACKEND_EXCEPTIONS as retry_exc:
                if self._swallow_enforcement_error(retry_exc, scope):
                    return
                raise
        except ValueError as exc:
            if self._swallow_enforcement_error(exc, scope):
                return
            raise

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
        if not self._enabled:
            return
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
        exempt_when: Callable[[falcon.Request], bool] | None = None,
        cost: int | Callable[[falcon.Request], int] = 1,
        methods: list[str] | tuple[str, ...] | None = None,
        per_method: bool = False,
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
            exempt_when: Optional request predicate that skips rate limiting
                when it returns ``True``.
            cost: Either a static hit cost or a request-based callable that
                returns the hit cost for each request.
            methods: Optional HTTP methods that should trigger the limit.
            per_method: Whether requests that share the same responder should
                keep separate counters per HTTP method.

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
            exempt_when=exempt_when,
            cost=cost,
            methods=methods,
            per_method=per_method,
        )
        return self._decorate_limit(resolved_limit)

    def shared_limit(
        self,
        limit_value: str,
        scope: str,
        key_func: Callable[[falcon.Request], str] | None = None,
        error_message: str | None = None,
        exempt_when: Callable[[falcon.Request], bool] | None = None,
        cost: int | Callable[[falcon.Request], int] = 1,
        methods: list[str] | tuple[str, ...] | None = None,
        per_method: bool = False,
    ) -> Callable[[Any], Any]:
        """Decorator to apply one shared limit bucket across multiple routes.

        Args:
            limit_value: Limit string understood by ``limits``, such as
                ``"5/minute"``.
            scope: Shared storage scope used by every decorated route.
            key_func: Optional override for client key extraction.
            error_message: Custom message for HTTP 429 responses.
            exempt_when: Optional request predicate that skips rate limiting
                when it returns ``True``.
            cost: Either a static hit cost or a request-based callable that
                returns the hit cost for each request.
            methods: Optional HTTP methods that should trigger the limit.
            per_method: Whether requests in the shared scope should keep
                separate counters per HTTP method.

        Returns:
            A decorator that wraps the target with shared-scope enforcement.

        Raises:
            ValueError: When ``scope`` is blank, ``limit_value`` is invalid, or
                a static ``cost`` is not a positive integer.
        """

        if not scope.strip():
            raise ValueError("scope must be a non-empty string")
        if isinstance(cost, int) and (isinstance(cost, bool) or cost <= 0):
            raise ValueError("cost must be a positive integer")

        rate_limit_item = parse(limit_value)
        resolved_limit = RateLimitDefinition(
            requests=rate_limit_item.amount,
            rate_limit_item=rate_limit_item,
            key_func=self._resolve_key_func(key_func),
            rejection_message=error_message or DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE,
            exempt_when=exempt_when,
            cost=cost,
            methods=self._normalize_methods(methods),
            per_method=per_method,
        )
        return self._decorate_limit(resolved_limit, shared_scope=scope)

    def _decorate_limit(
        self,
        resolved_limit: RateLimitDefinition,
        shared_scope: str | None = None,
    ) -> Callable[[Any], Any]:
        """Build a decorator that enforces a resolved limit definition.

        Args:
            resolved_limit: Fully resolved rate limit configuration.
            shared_scope: Optional shared storage scope. When omitted, each
                decorated responder uses its own ``__qualname__``.

        Returns:
            A decorator that applies the resolved limit to responders or
            resource classes.
        """

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
                scope = shared_scope or target.__qualname__
                self.enforce_limit(resolved_limit, scope, req, resp)
                return target(*args, **kwargs)

            @wraps(target)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # args = (self/resource, req, resp, ...) for bound methods
                if self._is_exempt_call(target, async_wrapper, args):
                    return await target(*args, **kwargs)
                req, resp = _get_request_response(args)
                scope = shared_scope or target.__qualname__
                await self.enforce_limit_async(resolved_limit, scope, req, resp)
                return await target(*args, **kwargs)

            _mark_rate_limited(target)
            if inspect.iscoroutinefunction(target):
                _mark_rate_limited(async_wrapper)
                return async_wrapper
            _mark_rate_limited(sync_wrapper)
            return sync_wrapper

        return decorator
