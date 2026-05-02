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
        methods: Optional HTTP method filter. ``None`` means all methods.
        per_method: Whether to include the request method in the rate-limit key.
    """

    requests: int
    rate_limit_item: RateLimitItem
    key_func: Callable[[falcon.Request], str]
    rejection_message: str
    methods: frozenset[str] | None = None
    per_method: bool = False
    exempt_when: Callable[[falcon.Request], bool] | None = None
    cost: int | Callable[[falcon.Request], int] = 1


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
    per_method: bool = False,
) -> str:
    """Build the composite key used to track rate limit counters.

    The key format is ``{scope}:{client_id}``, ensuring limits are tracked
    per-endpoint and per-client. If the key function returns a falsy value,
    ``"global"`` is used as the client identifier (consistent with slowapi).

    Args:
        req: The incoming Falcon request.
        scope: Typically the responder's ``__qualname__`` (e.g., ``Resource.on_get``).
        client_key_func: Function that extracts a client identifier from ``req``.
        per_method: Whether to include the uppercase request method in the key.

    Returns:
        A string key suitable for the ``limits`` storage backend.
    """
    client_id = client_key_func(req) or "global"
    if per_method:
        return f"{scope}:{req.method.upper()}:{client_id}"
    return f"{scope}:{client_id}"


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


def _should_skip_limit(
    req: falcon.Request,
    resolved_limit: RateLimitDefinition,
) -> bool:
    """Return whether this limit should be skipped before key resolution.

    Method filtering runs before conditional exemptions so requests outside an
    explicit method filter do not call user-provided exemption predicates.

    Args:
        req: The incoming Falcon request.
        resolved_limit: The limit definition to evaluate.

    Returns:
        ``True`` when this limit should not build a key or hit storage.
    """
    if (
        resolved_limit.methods is not None
        and req.method.upper() not in resolved_limit.methods
    ):
        return True
    return bool(
        resolved_limit.exempt_when is not None and resolved_limit.exempt_when(req)
    )


def _resolve_limit_cost(
    req: falcon.Request,
    limit: RateLimitDefinition,
) -> int:
    limit_cost: int | Callable[[falcon.Request], int] = limit.cost
    if callable(limit_cost):
        resolved_cost = limit_cost(req)
    else:
        return limit_cost
    if (
        type(resolved_cost) is bool
        or type(resolved_cost) is not int
        or resolved_cost <= 0
    ):
        raise ValueError(
            "Invalid resolved limit cost value. It should be a positive integer."
        )
    return resolved_cost


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
    if _should_skip_limit(req, resolved_limit):
        return
    key = _build_rate_limit_key(
        req,
        scope,
        resolved_limit.key_func,
        per_method=resolved_limit.per_method,
    )
    resolved_cost = _resolve_limit_cost(req, resolved_limit)
    allowed = limiter.hit(resolved_limit.rate_limit_item, key, cost=resolved_cost)
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
    if _should_skip_limit(req, resolved_limit):
        return
    key = _build_rate_limit_key(
        req,
        scope,
        resolved_limit.key_func,
        per_method=resolved_limit.per_method,
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
