import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient
from http import HTTPStatus

import pytest

from limiter.constants import EMPTY_METHODS_ERROR_MESSAGE
from limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


def test_class_level_methods_filter_limits_only_selected_method() -> None:
    limiter = FalconRateLimiter()

    @limiter.rate_limit(
        requests=1,
        per=relativedelta(seconds=1),
        methods=["GET"],
    )
    class MethodFilteredResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get ok"

        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post ok"

    app = falcon.App()
    app.add_route("/method-filtered", MethodFilteredResource())
    client = TestClient(app)

    assert client.get("/method-filtered").status_code == HTTP_200
    assert client.get("/method-filtered").status_code == HTTP_429

    assert client.post("/method-filtered").status_code == HTTP_200
    assert client.post("/method-filtered").status_code == HTTP_200
    assert client.post("/method-filtered").status_code == HTTP_200


def test_empty_methods_filter_raises() -> None:
    limiter = FalconRateLimiter()

    with pytest.raises(ValueError, match=EMPTY_METHODS_ERROR_MESSAGE):

        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            methods=[],
        )
        class MethodFilteredResource:
            def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
                resp.text = "get ok"
