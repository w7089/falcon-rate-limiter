"""
Standalone Falcon app used for end-to-end tests.

Client isolation: every request must include an X-Test-Client-Id header.
Each test generates a unique UUID so counters never bleed across tests.
"""

import os

import falcon
from dateutil.relativedelta import relativedelta

from falcon_rate_limiter import FalconRateLimitMiddleware, FalconRateLimiter

limiter = FalconRateLimiter()
redis_limiter = FalconRateLimiter(
    storage_uri=os.getenv("REDIS_STORAGE_URI", "redis://redis:6379/0")
)


def _client_key(req: falcon.Request) -> str:
    return req.get_header("X-Test-Client-Id") or req.remote_addr or "global"


default_limiter = FalconRateLimiter(
    default_requests=2,
    default_per=relativedelta(minutes=1),
    key_func=_client_key,
)
default_middleware = FalconRateLimitMiddleware(default_limiter)


class HealthResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"status": "ok"}


class LimitedResource:
    """3 requests per minute — tests both allowed and blocked paths."""

    @limiter.rate_limit(requests=3, per=relativedelta(minutes=1), key_func=_client_key)
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"message": "ok"}


class HeadersResource:
    """2 requests per minute — used to assert header values precisely."""

    @limiter.rate_limit(requests=2, per=relativedelta(minutes=1), key_func=_client_key)
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"message": "ok"}


class CustomErrorResource:
    """1 request per minute with a custom rejection message."""

    @limiter.rate_limit(
        requests=1,
        per=relativedelta(minutes=1),
        key_func=_client_key,
        error_message="slow down, please",
    )
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"message": "ok"}


class DefaultLimitedResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"message": "default ok"}


class RedisLimitedResource:
    """2 requests per minute using Redis-backed shared storage."""

    @redis_limiter.rate_limit(
        requests=2,
        per=relativedelta(minutes=1),
        key_func=_client_key,
    )
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"message": "redis ok"}


@default_limiter.exempt
class ExemptDefaultResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"message": "exempt ok"}


application = falcon.App(middleware=[default_middleware])
application.add_route("/health", HealthResource())
application.add_route("/limited", LimitedResource())
application.add_route("/headers", HeadersResource())
application.add_route("/custom-error", CustomErrorResource())
application.add_route("/default-limited", DefaultLimitedResource())
application.add_route("/redis-limited", RedisLimitedResource())
application.add_route("/default-exempt", ExemptDefaultResource())
