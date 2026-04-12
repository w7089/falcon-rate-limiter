import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient
from http import HTTPStatus

from limiter import FalconRateLimitMiddleware
from limiter.constants import DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
from limiter.core import FalconRateLimiter
from tests.test_app import (
    create_async_middleware_app,
    create_middleware_app,
)

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


def test_middleware_blocks_undecorated_route(middleware_client: TestClient) -> None:
    resp1 = middleware_client.get("/middleware-test")
    resp2 = middleware_client.get("/middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_429
    assert resp2.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_middleware_skips_decorated_route(middleware_client: TestClient) -> None:
    resp1 = middleware_client.get("/middleware-decorated")
    resp2 = middleware_client.get("/middleware-decorated")
    resp3 = middleware_client.get("/middleware-decorated")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_middleware_respects_limit_undecorated_routes_toggle() -> None:
    client = TestClient(create_middleware_app(limit_undecorated_routes=False))

    resp1 = client.get("/middleware-test")
    resp2 = client.get("/middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200


def test_default_limits_apply_to_undecorated_middleware_route() -> None:
    client = TestClient(
        create_middleware_app(
            default_requests=1,
            default_per=relativedelta(seconds=1),
        )
    )

    resp1 = client.get("/middleware-default")
    resp2 = client.get("/middleware-default")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_429
    assert resp2.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_exempt_decorator_skips_default_middleware_limits() -> None:
    client = TestClient(
        create_middleware_app(
            default_requests=1,
            default_per=relativedelta(seconds=1),
        )
    )

    resp1 = client.get("/middleware-exempt")
    resp2 = client.get("/middleware-exempt")
    resp3 = client.get("/middleware-exempt")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_200


def test_async_middleware_blocks_undecorated_route(
    async_middleware_client: TestClient,
) -> None:
    resp1 = async_middleware_client.get("/async-middleware-test")
    resp2 = async_middleware_client.get("/async-middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_429
    assert resp2.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_async_middleware_skips_decorated_route(
    async_middleware_client: TestClient,
) -> None:
    resp1 = async_middleware_client.get("/async-middleware-decorated")
    resp2 = async_middleware_client.get("/async-middleware-decorated")
    resp3 = async_middleware_client.get("/async-middleware-decorated")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_async_middleware_respects_limit_undecorated_routes_toggle() -> None:
    client = TestClient(create_async_middleware_app(limit_undecorated_routes=False))

    resp1 = client.get("/async-middleware-test")
    resp2 = client.get("/async-middleware-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200


def test_async_default_limits_apply_to_undecorated_middleware_route() -> None:
    client = TestClient(
        create_async_middleware_app(
            default_requests=1,
            default_per=relativedelta(seconds=1),
        )
    )

    resp1 = client.get("/async-middleware-default")
    resp2 = client.get("/async-middleware-default")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_429
    assert resp2.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_async_exempt_decorator_skips_default_middleware_limits() -> None:
    client = TestClient(
        create_async_middleware_app(
            default_requests=1,
            default_per=relativedelta(seconds=1),
        )
    )

    resp1 = client.get("/async-middleware-exempt")
    resp2 = client.get("/async-middleware-exempt")
    resp3 = client.get("/async-middleware-exempt")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_200


def test_exempt_decorator_supports_middleware_resource_instances() -> None:
    limiter = FalconRateLimiter(
        default_requests=1,
        default_per=relativedelta(seconds=1),
    )

    class SharedResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    exempt_resource = SharedResource()
    limited_resource = SharedResource()
    limiter.exempt(exempt_resource)

    app = falcon.App(middleware=[FalconRateLimitMiddleware(limiter)])
    app.add_route("/middleware-instance-exempt", exempt_resource)
    app.add_route("/middleware-instance-limited", limited_resource)
    client = TestClient(app)

    assert client.get("/middleware-instance-exempt").status_code == HTTP_200
    assert client.get("/middleware-instance-exempt").status_code == HTTP_200
    assert client.get("/middleware-instance-exempt").status_code == HTTP_200

    assert client.get("/middleware-instance-limited").status_code == HTTP_200
    assert client.get("/middleware-instance-limited").status_code == HTTP_429
