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
from typing import Sequence, cast


def _create_rate_limit_item(requests: int, per: relativedelta) -> RateLimitItem:
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


def _get_remote_address(req: falcon.Request) -> str:
    access_route = cast(Sequence[str] | None, getattr(req, "access_route", None))
    if access_route:
        return access_route[0]
    remote_addr = req.remote_addr
    return remote_addr if remote_addr is not None else "global"
