import asyncio
from collections.abc import Callable
from http import HTTPStatus
from typing import cast

import falcon
import falcon.asgi
from dateutil.relativedelta import relativedelta
from falcon import testing
from falcon.testing import TestClient
import pytest

from limiter import FalconRateLimitMiddleware
from limiter.constants import INVALID_LIMIT_COST_ERROR_MESSAGE
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


def test_sync_method_callable_cost_consumes_dynamic_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)

    class WeightedResource:
        @limiter.rate_limit(
            requests=5,
            per=relativedelta(minutes=1),
            cost=lambda req: int(req.get_header("X-Cost") or "1"),
        )
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.App()
    app.add_route("/weighted-callable", WeightedResource())
    client = TestClient(app)

    assert (
        client.post("/weighted-callable", headers={"X-Cost": "3"}).status_code
        == HTTP_200
    )
    assert (
        client.post("/weighted-callable", headers={"X-Cost": "3"}).status_code
        == HTTP_429
    )


def _zero_cost(req: falcon.Request) -> int:
    del req
    return 0


def _bool_cost(req: falcon.Request) -> bool:
    del req
    return True


@pytest.mark.parametrize(
    "cost",
    [
        _zero_cost,
        _bool_cost,
        cast(Callable[[falcon.Request], int], lambda req: 1.5),
    ],
    ids=["zero", "bool", "float"],
)
def test_sync_method_invalid_callable_cost_raises_value_error(
    cost: Callable[[falcon.Request], int],
) -> None:
    limiter = FalconRateLimiter(headers_enabled=False)

    class WeightedResource:
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    limit = limiter.create_limit(
        requests=5,
        per=relativedelta(minutes=1),
        cost=cost,
    )
    req = falcon.Request(testing.create_environ(path="/weighted-invalid-cost"))
    resp = falcon.Response()

    with pytest.raises(ValueError, match=INVALID_LIMIT_COST_ERROR_MESSAGE):
        limiter.enforce_limit(limit, WeightedResource.on_post.__qualname__, req, resp)


def test_async_method_static_cost_consumes_multiple_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)

    class WeightedResource:
        @limiter.rate_limit(
            requests=5,
            per=relativedelta(minutes=1),
            cost=2,
        )
        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.asgi.App()
    app.add_route("/async-weighted", WeightedResource())
    client = TestClient(app)

    assert client.post("/async-weighted").status_code == HTTP_200
    assert client.post("/async-weighted").status_code == HTTP_200
    assert client.post("/async-weighted").status_code == HTTP_429


def test_async_method_callable_cost_consumes_dynamic_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)

    class WeightedResource:
        @limiter.rate_limit(
            requests=5,
            per=relativedelta(minutes=1),
            cost=lambda req: int(req.get_header("X-Cost") or "1"),
        )
        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.asgi.App()
    app.add_route("/async-weighted-callable", WeightedResource())
    client = TestClient(app)

    assert (
        client.post("/async-weighted-callable", headers={"X-Cost": "3"}).status_code
        == HTTP_200
    )
    assert (
        client.post("/async-weighted-callable", headers={"X-Cost": "3"}).status_code
        == HTTP_429
    )


@pytest.mark.parametrize(
    "cost",
    [
        _zero_cost,
        _bool_cost,
        cast(Callable[[falcon.Request], int], lambda req: 1.5),
    ],
    ids=["zero", "bool", "float"],
)
def test_async_method_invalid_callable_cost_raises_value_error(
    cost: Callable[[falcon.Request], int],
) -> None:
    limiter = FalconRateLimiter(headers_enabled=False)

    class WeightedResource:
        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    limit = limiter.create_limit(
        requests=5,
        per=relativedelta(minutes=1),
        cost=cost,
    )
    req = falcon.Request(testing.create_environ(path="/async-weighted-invalid-cost"))
    resp = falcon.Response()

    with pytest.raises(ValueError, match=INVALID_LIMIT_COST_ERROR_MESSAGE):
        asyncio.run(
            limiter.enforce_limit_async(
                limit,
                WeightedResource.on_post.__qualname__,
                req,
                resp,
            )
        )


def test_sync_middleware_static_cost_consumes_multiple_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=5,
        per=relativedelta(minutes=1),
        cost=2,
    )

    class WeightedResource:
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.App(middleware=[middleware])
    app.add_route("/middleware-weighted", WeightedResource())
    client = TestClient(app)

    assert client.post("/middleware-weighted").status_code == HTTP_200
    assert client.post("/middleware-weighted").status_code == HTTP_200
    assert client.post("/middleware-weighted").status_code == HTTP_429


def test_sync_middleware_callable_cost_consumes_dynamic_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=5,
        per=relativedelta(minutes=1),
        cost=lambda req: int(req.get_header("X-Cost") or "1"),
    )

    class WeightedResource:
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.App(middleware=[middleware])
    app.add_route("/middleware-weighted-callable", WeightedResource())
    client = TestClient(app)

    assert (
        client.post(
            "/middleware-weighted-callable", headers={"X-Cost": "3"}
        ).status_code
        == HTTP_200
    )
    assert (
        client.post(
            "/middleware-weighted-callable", headers={"X-Cost": "3"}
        ).status_code
        == HTTP_429
    )


@pytest.mark.parametrize(
    "cost",
    [
        _zero_cost,
        _bool_cost,
        cast(Callable[[falcon.Request], int], lambda req: 1.5),
    ],
    ids=["zero", "bool", "float"],
)
def test_sync_middleware_invalid_callable_cost_raises_value_error(
    cost: Callable[[falcon.Request], int],
) -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=5,
        per=relativedelta(minutes=1),
        cost=cost,
    )

    class WeightedResource:
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    req = falcon.Request(
        testing.create_environ(
            path="/middleware-weighted-invalid-cost",
            method="POST",
        )
    )
    resp = falcon.Response()

    with pytest.raises(ValueError, match=INVALID_LIMIT_COST_ERROR_MESSAGE):
        middleware.process_resource(req, resp, WeightedResource(), {})


def test_async_middleware_static_cost_consumes_multiple_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=5,
        per=relativedelta(minutes=1),
        cost=2,
    )

    class WeightedResource:
        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.asgi.App(middleware=[middleware])
    app.add_route("/async-middleware-weighted", WeightedResource())
    client = TestClient(app)

    assert client.post("/async-middleware-weighted").status_code == HTTP_200
    assert client.post("/async-middleware-weighted").status_code == HTTP_200
    assert client.post("/async-middleware-weighted").status_code == HTTP_429


def test_async_middleware_callable_cost_consumes_dynamic_quota_units() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=5,
        per=relativedelta(minutes=1),
        cost=lambda req: int(req.get_header("X-Cost") or "1"),
    )

    class WeightedResource:
        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    app = falcon.asgi.App(middleware=[middleware])
    app.add_route("/async-middleware-weighted-callable", WeightedResource())
    client = TestClient(app)

    assert (
        client.post(
            "/async-middleware-weighted-callable",
            headers={"X-Cost": "3"},
        ).status_code
        == HTTP_200
    )
    assert (
        client.post(
            "/async-middleware-weighted-callable",
            headers={"X-Cost": "3"},
        ).status_code
        == HTTP_429
    )


@pytest.mark.parametrize(
    "cost",
    [
        _zero_cost,
        _bool_cost,
        cast(Callable[[falcon.Request], int], lambda req: 1.5),
    ],
    ids=["zero", "bool", "float"],
)
def test_async_middleware_invalid_callable_cost_raises_value_error(
    cost: Callable[[falcon.Request], int],
) -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=5,
        per=relativedelta(minutes=1),
        cost=cost,
    )

    class WeightedResource:
        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "created"

    req = falcon.Request(
        testing.create_environ(
            path="/async-middleware-weighted-invalid-cost",
            method="POST",
        )
    )
    resp = falcon.Response()

    with pytest.raises(ValueError, match=INVALID_LIMIT_COST_ERROR_MESSAGE):
        asyncio.run(
            middleware.process_resource_async(req, resp, WeightedResource(), {})
        )
