from dateutil.relativedelta import relativedelta
from limits import (
    RateLimitItem,
    RateLimitItemPerSecond,
    RateLimitItemPerMinute,
    RateLimitItemPerHour,
    RateLimitItemPerDay,
    RateLimitItemPerMonth,
    RateLimitItemPerYear,
)


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
