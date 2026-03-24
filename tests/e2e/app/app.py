"""
Standalone Falcon app used for end-to-end tests.

Client isolation: every request must include an X-Test-Client-Id header.
Each test generates a unique UUID so counters never bleed across tests.
"""

import falcon
from dateutil.relativedelta import relativedelta

from limiter import FalconRateLimiter

limiter = FalconRateLimiter()


def _client_key(req: falcon.Request) -> str:
    return req.get_header("X-Test-Client-Id") or req.remote_addr or "global"


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


application = falcon.App()
application.add_route("/health", HealthResource())
application.add_route("/limited", LimitedResource())
application.add_route("/headers", HeadersResource())
application.add_route("/custom-error", CustomErrorResource())
