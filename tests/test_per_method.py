import falcon
import falcon.asgi
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient
from limits.storage import MemoryStorage
from typing import Any, cast

from limiter import FalconRateLimitMiddleware
from limiter.core import FalconRateLimiter


class RecordingMemoryStorage(MemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []

    def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        self.keys.append(key)
        return super().incr(key, expiry, amount=amount)


def test_sync_decorator_per_method_adds_method_to_storage_key() -> None:
    storage = RecordingMemoryStorage()
    limiter = FalconRateLimiter(storage=storage, headers_enabled=False)

    @limiter.rate_limit(
        requests=5,
        per=relativedelta(seconds=1),
        key_func=lambda req: "client-a",
        per_method=True,
    )
    class PerMethodResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get ok"

        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post ok"

    app = falcon.App()
    app.add_route("/per-method", PerMethodResource())
    client = TestClient(app)

    assert client.get("/per-method").status_code == 200
    assert client.post("/per-method").status_code == 200

    assert any(":GET:client-a" in key for key in storage.keys)
    assert any(":POST:client-a" in key for key in storage.keys)


def test_sync_decorator_default_key_does_not_include_request_method() -> None:
    storage = RecordingMemoryStorage()
    limiter = FalconRateLimiter(storage=storage, headers_enabled=False)

    @limiter.rate_limit(
        requests=5,
        per=relativedelta(seconds=1),
        key_func=lambda req: "client-a",
    )
    class PerMethodResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get ok"

    app = falcon.App()
    app.add_route("/default-method-key", PerMethodResource())
    client = TestClient(app)

    assert client.get("/default-method-key").status_code == 200
    assert not any(":GET:client-a" in key for key in storage.keys)


def test_async_decorator_per_method_adds_method_to_storage_key() -> None:
    storage = RecordingMemoryStorage()
    limiter = FalconRateLimiter(storage=storage, headers_enabled=False)

    @limiter.rate_limit(
        requests=5,
        per=relativedelta(seconds=1),
        key_func=lambda req: "client-a",
        per_method=True,
    )
    class AsyncPerMethodResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get ok"

        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post ok"

    app = falcon.asgi.App()
    app.add_route("/async-per-method", AsyncPerMethodResource())
    client = TestClient(app)

    assert client.get("/async-per-method").status_code == 200
    assert client.post("/async-per-method").status_code == 200

    assert any(":GET:client-a" in key for key in storage.keys)
    assert any(":POST:client-a" in key for key in storage.keys)


def test_middleware_per_method_adds_method_to_storage_key() -> None:
    storage = RecordingMemoryStorage()
    limiter = FalconRateLimiter(storage=storage, headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=5,
        per=relativedelta(seconds=1),
        key_func=lambda req: "client-a",
        per_method=True,
    )

    class PerMethodMiddlewareResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get ok"

        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post ok"

    app = falcon.App(middleware=[middleware])
    app.add_route("/middleware-per-method", PerMethodMiddlewareResource())
    client = TestClient(app)

    assert client.get("/middleware-per-method").status_code == 200
    assert client.post("/middleware-per-method").status_code == 200

    assert any(":GET:client-a" in key for key in storage.keys)
    assert any(":POST:client-a" in key for key in storage.keys)


def test_middleware_per_method_counts_methods_separately() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=1,
        per=relativedelta(seconds=1),
        key_func=lambda req: "client-a",
        per_method=True,
    )

    class PerMethodMiddlewareResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get ok"

        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post ok"

    app = falcon.App(middleware=[middleware])
    app.add_route("/middleware-per-method-counts", PerMethodMiddlewareResource())
    client = TestClient(app)

    assert client.get("/middleware-per-method-counts").status_code == 200
    assert client.get("/middleware-per-method-counts").status_code == 429
    assert client.post("/middleware-per-method-counts").status_code == 200
    assert client.post("/middleware-per-method-counts").status_code == 429


def test_async_middleware_per_method_counts_methods_separately() -> None:
    storage = RecordingMemoryStorage()
    limiter = FalconRateLimiter(storage=storage, headers_enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=1,
        per=relativedelta(seconds=1),
        key_func=lambda req: "client-a",
        per_method=True,
    )

    class AsyncPerMethodMiddlewareResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get ok"

        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post ok"

    app = falcon.asgi.App(middleware=cast(list[Any], [middleware]))
    app.add_route(
        "/async-middleware-per-method-counts", AsyncPerMethodMiddlewareResource()
    )
    client = TestClient(app)

    assert client.get("/async-middleware-per-method-counts").status_code == 200
    assert client.get("/async-middleware-per-method-counts").status_code == 429
    assert client.post("/async-middleware-per-method-counts").status_code == 200
    assert client.post("/async-middleware-per-method-counts").status_code == 429

    assert any(":GET:client-a" in key for key in storage.keys)
    assert any(":POST:client-a" in key for key in storage.keys)
