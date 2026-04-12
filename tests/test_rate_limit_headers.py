import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient
from http import HTTPStatus

from limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


def test_rate_limit_headers_on_allowed_request(client: TestClient) -> None:
    resp = client.get("/test")
    assert resp.status_code == HTTP_200
    assert resp.headers["X-RateLimit-Limit"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Reset" in resp.headers


def test_rate_limit_headers_on_blocked_request(client: TestClient) -> None:
    client.get("/test")
    client.get("/test")
    resp = client.get("/test")
    assert resp.status_code == HTTP_429
    assert resp.headers["X-RateLimit-Limit"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in resp.headers
    assert "Retry-After" in resp.headers


def test_headers_disabled() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)

    class NoHeaderResource:
        @limiter.rate_limit(requests=5, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/no-headers", NoHeaderResource())
    client = TestClient(app)
    resp = client.get("/no-headers")
    assert resp.status_code == HTTP_200
    assert "X-RateLimit-Limit" not in resp.headers
    assert "X-RateLimit-Remaining" not in resp.headers


def test_async_rate_limit_headers_on_allowed_request(async_client: TestClient) -> None:
    resp = async_client.get("/async-test")
    assert resp.status_code == HTTP_200
    assert resp.headers["X-RateLimit-Limit"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Reset" in resp.headers


def test_async_rate_limit_headers_on_blocked_request(async_client: TestClient) -> None:
    async_client.get("/async-test")
    async_client.get("/async-test")
    resp = async_client.get("/async-test")
    assert resp.status_code == HTTP_429
    assert resp.headers["X-RateLimit-Limit"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in resp.headers
    assert "Retry-After" in resp.headers
