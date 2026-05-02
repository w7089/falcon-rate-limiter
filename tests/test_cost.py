from http import HTTPStatus

import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient

from limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


def test_sync_method_static_cost_consumes_multiple_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)

    class WeightedResource:
        @limiter.rate_limit(
            requests=5,
            per=relativedelta(minutes=1),
            cost=2,
        )
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.App()
    app.add_route("/weighted", WeightedResource())
    client = TestClient(app)

    assert client.post("/weighted").status_code == HTTP_200
    assert client.post("/weighted").status_code == HTTP_200
    assert client.post("/weighted").status_code == HTTP_429
