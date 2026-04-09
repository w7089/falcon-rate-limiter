import asyncio
from dataclasses import dataclass
import time
from typing import Any, Callable, cast

import falcon
from limits import RateLimitItem
from limits.strategies import FixedWindowRateLimiter
from limits.util import WindowStats

_RATE_LIMIT_DECORATED_ATTR = "__falcon_rate_limit_decorated__"
_RATE_LIMIT_EXEMPT_ATTR = "__falcon_rate_limit_exempt__"


@dataclass(frozen=True)
class RateLimitDefinition:
    """Immutable container for a resolved rate limit configuration.

    Attributes:
        requests: Maximum number of requests allowed in the time window.
        rate_limit_item: The ``limits`` library item used for storage lookups.
        key_func: Function that extracts the client identifier from a request.
        rejection_message: Message returned in HTTP 429 responses.
        exempt_when: Optional request predicate that skips rate limiting when
            it returns ``True``.
        methods: Optional uppercase HTTP methods that should trigger the limit.
            ``None`` means the limit applies to every request method.
        per_method: Whether requests that share the same responder should use
            separate counters per HTTP method.
    """

    requests: int
    rate_limit_item: RateLimitItem
    key_func: Callable[[falcon.Request], str]
    rejection_message: str
    exempt_when: Callable[[falcon.Request], bool] | None = None
    methods: frozenset[str] | None = None
    per_method: bool = False


def _get_request_response(
    args: tuple[Any, ...],
) -> tuple[falcon.Request, falcon.Response]:
    """Extract the Falcon request and response from responder arguments.

    Falcon responder methods have the signature ``on_*(self, req, resp, ...)``.
    When the wrapper captures ``*args``, the layout is:
        args[0] -> resource instance (self)
        args[1] -> falcon.Request
        args[2] -> falcon.Response

    Args:
        args: Positional arguments forwarded to the wrapped responder.

    Returns:
        A tuple of (request, response).

    Raises:
        TypeError: When fewer than 3 positional arguments are provided,
            indicating the wrapper was applied to an incompatible callable.
    """
    if len(args) >= 3:
        # args[1] is req, args[2] is resp (args[0] is self/resource instance)
        return cast(falcon.Request, args[1]), cast(falcon.Response, args[2])
    raise TypeError(
        "Wrapped Falcon responder is missing request/response arguments (expected self, req, resp)"
    )


def _mark_rate_limited(target: Any) -> None:
    """Mark a callable or class as having an explicit rate limit decorator.

    This marker is checked by middleware to avoid double-limiting routes
    that already have decorator-based limits.

    Args:
        target: Responder function, wrapper, or resource class to mark.
    """
    setattr(target, _RATE_LIMIT_DECORATED_ATTR, True)


def _is_rate_limited(target: Any) -> bool:
    """Return whether a target has an explicit rate limit decorator.

    Args:
        target: Callable or class to check for the rate-limited marker.

    Returns:
        ``True`` if ``@limiter.rate_limit`` was applied, otherwise ``False``.
    """
    return bool(getattr(target, _RATE_LIMIT_DECORATED_ATTR, False))


def _mark_rate_limit_exempt(target: Any) -> None:
    """Mark a responder, resource instance, or resource class as exempt.

    Args:
        target: Callable or object that should bypass decorator and middleware
            rate-limit checks.

    Returns:
        None.

    Raises:
        AttributeError: Raised by ``setattr`` when the target does not allow
            attribute assignment.
    """
    setattr(target, _RATE_LIMIT_EXEMPT_ATTR, True)


def _is_rate_limit_exempt(target: Any) -> bool:
    """Return whether a target has been marked as rate-limit exempt.

    Args:
        target: Callable or object to inspect for the internal exemption flag.

    Returns:
        ``True`` when the target has been marked with ``@limiter.exempt``,
        otherwise ``False``.

    Raises:
        None.
    """
    return bool(getattr(target, _RATE_LIMIT_EXEMPT_ATTR, False))


def _build_rate_limit_key(
    req: falcon.Request,
    scope: str,
    client_key_func: Callable[[falcon.Request], str],
) -> str:
    """Build the composite key used to track rate limit counters.

    The key format is ``{scope}:{client_id}``, ensuring limits are tracked
    per-endpoint and per-client. If the key function returns a falsy value,
    ``"global"`` is used as the client identifier (consistent with slowapi).

    Args:
        req: The incoming Falcon request.
        scope: Typically the responder's ``__qualname__`` (e.g., ``Resource.on_get``).
        client_key_func: Function that extracts a client identifier from ``req``.

    Returns:
        A string key suitable for the ``limits`` storage backend.
    """
    client_id = client_key_func(req) or "global"
    return f"{scope}:{client_id}"


def _request_method_matches_limit(
    req: falcon.Request, resolved_limit: RateLimitDefinition
) -> bool:
    """Return whether a request method should be checked against a limit.

    Args:
        req: The incoming Falcon request.
        resolved_limit: The limit configuration being evaluated.

    Returns:
        ``True`` when the limit applies to the request method, otherwise ``False``.
    """

    if resolved_limit.methods is None:
        return True
    return req.method.upper() in resolved_limit.methods


def _request_is_exempt_from_limit(
    req: falcon.Request, resolved_limit: RateLimitDefinition
) -> bool:
    """Return whether a request should bypass a configured rate limit.

    Args:
        req: The incoming Falcon request.
        resolved_limit: The limit configuration being evaluated.

    Returns:
        ``True`` when ``exempt_when`` is configured and returns ``True`` for the
        request, otherwise ``False``.
    """

    if resolved_limit.exempt_when is None:
        return False
    return resolved_limit.exempt_when(req)


def _scope_for_limit(
    req: falcon.Request,
    scope: str,
    resolved_limit: RateLimitDefinition,
) -> str:
    """Return the storage scope for a request and limit configuration.

    Args:
        req: The incoming Falcon request.
        scope: Base endpoint scope, usually the responder ``__qualname__``.
        resolved_limit: The limit configuration being enforced.

    Returns:
        The base scope, or a method-specific scope when ``per_method`` is enabled.
    """

    if not resolved_limit.per_method:
        return scope
    return f"{scope}:{req.method.upper()}"


def _set_rate_limit_headers(
    resp: falcon.Response,
    stats: WindowStats,
    requests: int,
) -> None:
    """Add standard rate limit headers to the response.

    Headers set:
        - ``X-RateLimit-Limit``: Maximum requests allowed in the window.
        - ``X-RateLimit-Remaining``: Requests remaining in the current window.
        - ``X-RateLimit-Reset``: Unix timestamp when the window resets.

    Args:
        resp: The Falcon response object to modify.
        stats: Window statistics from the ``limits`` library.
        requests: The configured limit (max requests per window).
    """
    reset_time = int(stats.reset_time)
    resp.set_header("X-RateLimit-Limit", str(requests))
    resp.set_header("X-RateLimit-Remaining", str(stats.remaining))
    resp.set_header("X-RateLimit-Reset", str(reset_time))


def _retry_after_seconds(stats: WindowStats | None) -> int | None:
    """Compute the Retry-After value in seconds.

    Args:
        stats: Window statistics from the ``limits`` library, or ``None``.

    Returns:
        Seconds until the rate limit window resets, or ``None`` if stats
        are unavailable. Returns at least 0 to avoid negative values.
    """
    if stats is None:
        return None
    return max(0, int(stats.reset_time - time.time()))


def _check_rate_limit(
    limiter: FixedWindowRateLimiter,
    resolved_limit: RateLimitDefinition,
    headers_enabled: bool,
    scope: str,
    req: falcon.Request,
    resp: falcon.Response,
) -> None:
    """Check and enforce a rate limit synchronously.

    This function increments the counter for the client/scope key and raises
    ``falcon.HTTPTooManyRequests`` if the limit is exceeded.

    Args:
        limiter: The fixed-window rate limiter strategy instance.
        resolved_limit: The limit definition containing the rate and key func.
        headers_enabled: Whether to add X-RateLimit-* headers to the response.
        scope: Identifier for the endpoint (usually ``__qualname__``).
        req: The incoming Falcon request.
        resp: The Falcon response (headers may be modified).

    Raises:
        falcon.HTTPTooManyRequests: When the rate limit is exceeded.
    """
    if not _request_method_matches_limit(req, resolved_limit):
        return
    if _request_is_exempt_from_limit(req, resolved_limit):
        return

    key = _build_rate_limit_key(
        req,
        _scope_for_limit(req, scope, resolved_limit),
        resolved_limit.key_func,
    )
    allowed = limiter.hit(resolved_limit.rate_limit_item, key)
    stats: WindowStats | None = None
    if headers_enabled or not allowed:
        stats = limiter.get_window_stats(resolved_limit.rate_limit_item, key)
    if headers_enabled and stats is not None:
        _set_rate_limit_headers(resp, stats, resolved_limit.requests)
    if not allowed:
        raise falcon.HTTPTooManyRequests(
            description=resolved_limit.rejection_message,
            retry_after=_retry_after_seconds(stats),
        )


async def _check_rate_limit_async(
    limiter: FixedWindowRateLimiter,
    resolved_limit: RateLimitDefinition,
    headers_enabled: bool,
    scope: str,
    req: falcon.Request,
    resp: falcon.Response,
) -> None:
    """Check and enforce a rate limit asynchronously.

    The ``limits`` library is synchronous, so blocking calls are offloaded
    to a thread pool via ``asyncio.to_thread`` to avoid blocking the event
    loop in ASGI applications.

    Args:
        limiter: The fixed-window rate limiter strategy instance.
        resolved_limit: The limit definition containing the rate and key func.
        headers_enabled: Whether to add X-RateLimit-* headers to the response.
        scope: Identifier for the endpoint (usually ``__qualname__``).
        req: The incoming Falcon request.
        resp: The Falcon response (headers may be modified).

    Raises:
        falcon.HTTPTooManyRequests: When the rate limit is exceeded.
    """
    if not _request_method_matches_limit(req, resolved_limit):
        return
    if _request_is_exempt_from_limit(req, resolved_limit):
        return

    key = _build_rate_limit_key(
        req,
        _scope_for_limit(req, scope, resolved_limit),
        resolved_limit.key_func,
    )

    def _hit_and_stats() -> tuple[bool, WindowStats | None]:
        """Run blocking limiter calls in a thread pool."""
        allowed = limiter.hit(resolved_limit.rate_limit_item, key)
        stats = (
            limiter.get_window_stats(resolved_limit.rate_limit_item, key)
            if headers_enabled or not allowed
            else None
        )
        return allowed, stats

    allowed, stats = await asyncio.to_thread(_hit_and_stats)
    if headers_enabled and stats is not None:
        _set_rate_limit_headers(resp, stats, resolved_limit.requests)
    if not allowed:
        raise falcon.HTTPTooManyRequests(
            description=resolved_limit.rejection_message,
            retry_after=_retry_after_seconds(stats),
        )
