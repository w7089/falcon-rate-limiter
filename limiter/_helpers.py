import asyncio
from dataclasses import dataclass
import time
from typing import Any, Callable, cast

import falcon
from limits import RateLimitItem
from limits.strategies import FixedWindowRateLimiter
from limits.util import WindowStats

_RATE_LIMIT_DECORATED_ATTR = "__falcon_rate_limit_decorated__"


@dataclass(frozen=True)
class RateLimitDefinition:
    requests: int
    rate_limit_item: RateLimitItem
    key_func: Callable[[falcon.Request], str]
    rejection_message: str


def _get_request_response(
    args: tuple[Any, ...],
) -> tuple[falcon.Request, falcon.Response]:
    if len(args) >= 3:
        return cast(falcon.Request, args[1]), cast(falcon.Response, args[2])
    raise TypeError(
        "Wrapped Falcon responder is missing request/response arguments (expected self, req, resp)"
    )


def _mark_rate_limited(target: Any) -> None:
    setattr(target, _RATE_LIMIT_DECORATED_ATTR, True)


def _is_rate_limited(target: Any) -> bool:
    return bool(getattr(target, _RATE_LIMIT_DECORATED_ATTR, False))


def _build_rate_limit_key(
    req: falcon.Request,
    scope: str,
    client_key_func: Callable[[falcon.Request], str],
) -> str:
    client_id = client_key_func(req) or "global"
    return f"{scope}:{client_id}"


def _set_rate_limit_headers(
    resp: falcon.Response,
    stats: WindowStats,
    requests: int,
) -> None:
    reset_time = int(stats.reset_time)
    resp.set_header("X-RateLimit-Limit", str(requests))
    resp.set_header("X-RateLimit-Remaining", str(stats.remaining))
    resp.set_header("X-RateLimit-Reset", str(reset_time))


def _retry_after_seconds(stats: WindowStats | None) -> int | None:
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
    key = _build_rate_limit_key(req, scope, resolved_limit.key_func)
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
    key = _build_rate_limit_key(req, scope, resolved_limit.key_func)

    def _hit_and_stats() -> tuple[bool, WindowStats | None]:
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
