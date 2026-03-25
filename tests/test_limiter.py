import pytest
from falcon.testing import TestClient
from falcon import App
from falcon.asgi import App as ASGIApp
from http import HTTPStatus

from limiter.core import FalconRateLimiter
from tests.test_app import (
    create_app,
    create_async_app,
    create_async_middleware_app,
    create_middleware_app,
)

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


@pytest.fixture
def limiter() -> FalconRateLimiter:
    return FalconRateLimiter()


@pytest.fixture
def falcon_app() -> App:
    return create_app()


@pytest.fixture
def client(falcon_app: App) -> TestClient:
    return TestClient(falcon_app)


@pytest.fixture
def async_falcon_app() -> ASGIApp:
    return create_async_app()


@pytest.fixture
def async_client(async_falcon_app: ASGIApp) -> TestClient:
    return TestClient(async_falcon_app)


@pytest.fixture
def middleware_client() -> TestClient:
    return TestClient(create_middleware_app())


@pytest.fixture
def async_middleware_client() -> TestClient:
    return TestClient(create_async_middleware_app())


def test_rate_limit_allows_requests(client: TestClient) -> None:
    resp1 = client.get("/test")
    resp2 = client.get("/test")
    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200


def test_rate_limit_blocks_after_limit(client: TestClient) -> None:
    client.get("/test")
    client.get("/test")
    resp3 = client.get("/test")
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == "Rate limit exceeded"


def test_class_level_rate_limit_blocks_after_limit(client: TestClient) -> None:
    resp1 = client.get("/class-test")
    resp2 = client.get("/class-test")
    resp3 = client.get("/class-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == "Rate limit exceeded"


def test_async_rate_limit_allows_requests(async_client: TestClient) -> None:
    resp1 = async_client.get("/async-test")
    resp2 = async_client.get("/async-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200


def test_async_rate_limit_blocks_after_limit(async_client: TestClient) -> None:
    async_client.get("/async-test")
    async_client.get("/async-test")
    resp3 = async_client.get("/async-test")

    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == "Rate limit exceeded"


def test_async_class_level_rate_limit_blocks_after_limit(
    async_client: TestClient,
) -> None:
    resp1 = async_client.get("/async-class-test")
    resp2 = async_client.get("/async-class-test")
    resp3 = async_client.get("/async-class-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == "Rate limit exceeded"


def test_per_client_keys_isolate_limits(client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = client.get("/per-client", headers=headers_a)
    second_a = client.get("/per-client", headers=headers_a)
    first_b = client.get("/per-client", headers=headers_b)

    assert first_a.status_code == HTTP_200
    assert second_a.status_code == HTTP_429
    assert "Rate limit exceeded" in second_a.text
    assert first_b.status_code == HTTP_200


def test_per_client_keys_isolate_class_decorated_limits(client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = client.get("/class-per-client", headers=headers_a)
    second_a = client.get("/class-per-client", headers=headers_a)
    first_b = client.get("/class-per-client", headers=headers_b)

    assert first_a.status_code == HTTP_200
    assert second_a.status_code == HTTP_429
    assert "Rate limit exceeded" in second_a.text
    assert first_b.status_code == HTTP_200


def test_async_per_client_keys_isolate_limits(async_client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = async_client.get("/async-per-client", headers=headers_a)
    second_a = async_client.get("/async-per-client", headers=headers_a)
    first_b = async_client.get("/async-per-client", headers=headers_b)

    assert first_a.status_code == HTTP_200
    assert second_a.status_code == HTTP_429
    assert second_a.json["description"] == "Rate limit exceeded"
    assert first_b.status_code == HTTP_200


def test_custom_error_message(client: TestClient) -> None:
    client.get("/custom-message")
    resp = client.get("/custom-message")
    assert resp.status_code == HTTP_429
    assert resp.json["description"] == "Too fast, slow down"


def test_async_custom_error_message(async_client: TestClient) -> None:
    async_client.get("/async-custom-message")
    resp = async_client.get("/async-custom-message")
    assert resp.status_code == HTTP_429
    assert resp.json["description"] == "Async too fast"


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


def test_headers_disabled(falcon_app: App) -> None:
    from limiter.core import FalconRateLimiter
    from dateutil.relativedelta import relativedelta
    import falcon

    limiter = FalconRateLimiter(headers_enabled=False)

    class NoHeaderResource:
        @limiter.rate_limit(requests=5, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/no-headers", NoHeaderResource())
    c = TestClient(app)
    resp = c.get("/no-headers")
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


def test_middleware_blocks_undecorated_route(middleware_client: TestClient) -> None:
    resp1 = middleware_client.get("/middleware-test")
    resp2 = middleware_client.get("/middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_429
    assert resp2.json["description"] == "Rate limit exceeded"


def test_middleware_skips_decorated_route(middleware_client: TestClient) -> None:
    resp1 = middleware_client.get("/middleware-decorated")
    resp2 = middleware_client.get("/middleware-decorated")
    resp3 = middleware_client.get("/middleware-decorated")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == "Rate limit exceeded"


def test_middleware_respects_limit_undecorated_routes_toggle() -> None:
    client = TestClient(create_middleware_app(limit_undecorated_routes=False))

    resp1 = client.get("/middleware-test")
    resp2 = client.get("/middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200


def test_async_middleware_blocks_undecorated_route(
    async_middleware_client: TestClient,
) -> None:
    resp1 = async_middleware_client.get("/async-middleware-test")
    resp2 = async_middleware_client.get("/async-middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_429
    assert resp2.json["description"] == "Rate limit exceeded"


def test_async_middleware_skips_decorated_route(
    async_middleware_client: TestClient,
) -> None:
    resp1 = async_middleware_client.get("/async-middleware-decorated")
    resp2 = async_middleware_client.get("/async-middleware-decorated")
    resp3 = async_middleware_client.get("/async-middleware-decorated")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == "Rate limit exceeded"


def test_async_middleware_respects_limit_undecorated_routes_toggle() -> None:
    client = TestClient(create_async_middleware_app(limit_undecorated_routes=False))

    resp1 = client.get("/async-middleware-test")
    resp2 = client.get("/async-middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
