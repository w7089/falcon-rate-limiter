from dateutil.relativedelta import relativedelta
import falcon
from limits import (
    RateLimitItem,
    RateLimitItemPerSecond,
    RateLimitItemPerMinute,
    RateLimitItemPerHour,
    RateLimitItemPerDay,
    RateLimitItemPerMonth,
    RateLimitItemPerYear,
)
from typing import Sequence, cast, Iterable

from falcon_rate_limiter.constants import EMPTY_METHODS_ERROR_MESSAGE


def _create_rate_limit_item(requests: int, per: relativedelta) -> RateLimitItem:
    """Create a ``limits`` library RateLimitItem from a relativedelta.

    Maps the largest non-zero field in the relativedelta to the appropriate
    ``limits`` item class (per-second, per-minute, etc.).

    Args:
        requests: Maximum requests allowed in the time window.
        per: Time window duration with exactly one non-zero field.

    Returns:
        A ``RateLimitItem`` configured for the specified granularity.

    Raises:
        ValueError: When no supported time field is set in ``per``.
    """
    if per.seconds:
        return RateLimitItemPerSecond(requests)
    elif per.minutes:
        return RateLimitItemPerMinute(requests)
    elif per.hours:
        return RateLimitItemPerHour(requests)
    elif per.days:
        return RateLimitItemPerDay(requests)
    elif per.months:
        return RateLimitItemPerMonth(requests)
    elif per.years:
        return RateLimitItemPerYear(requests)
    else:
        raise ValueError(
            "Invalid time delta: must specify seconds, minutes, hours, days, months, or years"
        )


def get_remote_address(req: falcon.Request) -> str:
    """Extract the client IP address from a Falcon request.

    Prefers ``access_route[0]`` (first IP in X-Forwarded-For chain) when
    available, falling back to ``remote_addr``. Returns ``"global"`` if
    no address can be determined (consistent with slowapi's fallback).

    Args:
        req: The incoming Falcon request.

    Returns:
        A string identifier for the client, suitable for rate limit keys.
    """
    # access_route contains IPs from X-Forwarded-For; first is the original client
    access_route = cast(Sequence[str] | None, getattr(req, "access_route", None))
    if access_route:
        return access_route[0]
    remote_addr = req.remote_addr
    return remote_addr if remote_addr is not None else "global"


def _normalize_methods(methods: Iterable[str] | None) -> frozenset[str] | None:
    """Normalize an optional HTTP method filter.

    ``None`` means no method filter. A provided iterable must contain at least
    one method, and methods are stored uppercase for request-time comparison.
    """
    if methods is None:
        return None

    normalized = frozenset(method.upper() for method in methods)
    if not normalized:
        raise ValueError(EMPTY_METHODS_ERROR_MESSAGE)
    return normalized
