from http import HTTPStatus

import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient

from limiter.constants import DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
from limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


def test_sync_shared_limit_uses_one_bucket_across_two_routes() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=5,
        per=relativedelta(minutes=1),
        scope="api-v1",
    )

    class SearchResource:
        @shared_limit
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "search"

    class SuggestResource:
        @shared_limit
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "suggest"

    app = falcon.App()
    app.add_route("/search", SearchResource())
    app.add_route("/suggest", SuggestResource())
    client = TestClient(app)

    for _ in range(5):
        assert client.get("/search").status_code == HTTP_200

    blocked = client.get("/suggest")

    assert blocked.status_code == HTTP_429
    assert blocked.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
