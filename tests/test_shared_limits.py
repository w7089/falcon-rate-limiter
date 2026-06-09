from http import HTTPStatus

import falcon
import falcon.asgi
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient

from falcon_rate_limiter.constants import DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
from falcon_rate_limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS
INTERNAL_HEADERS = {"X-Internal": "true"}


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


def test_class_shared_limit_uses_one_bucket_across_resource_methods() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=2,
        per=relativedelta(minutes=1),
        scope="shared-resource",
    )

    @shared_limit
    class SharedResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get"

        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post"

    app = falcon.App()
    app.add_route("/shared", SharedResource())
    client = TestClient(app)

    assert client.get("/shared").status_code == HTTP_200
    assert client.post("/shared").status_code == HTTP_200

    blocked = client.get("/shared")

    assert blocked.status_code == HTTP_429
    assert blocked.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_async_shared_limit_uses_one_bucket_across_two_routes() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=2,
        per=relativedelta(minutes=1),
        scope="async-api-v1",
    )

    class SearchResource:
        @shared_limit
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "search"

    class SuggestResource:
        @shared_limit
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "suggest"

    app = falcon.asgi.App()
    app.add_route("/search", SearchResource())
    app.add_route("/suggest", SuggestResource())
    client = TestClient(app)

    assert client.get("/search").status_code == HTTP_200
    assert client.get("/search").status_code == HTTP_200

    blocked = client.get("/suggest")

    assert blocked.status_code == HTTP_429
    assert blocked.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_shared_limit_per_method_counts_methods_separately() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=1,
        per=relativedelta(minutes=1),
        scope="per-method-shared",
        per_method=True,
    )

    @shared_limit
    class SharedMethodResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "get"

        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "post"

    app = falcon.App()
    app.add_route("/shared-method", SharedMethodResource())
    client = TestClient(app)

    assert client.get("/shared-method").status_code == HTTP_200
    assert client.get("/shared-method").status_code == HTTP_429
    assert client.post("/shared-method").status_code == HTTP_200
    assert client.post("/shared-method").status_code == HTTP_429


def test_shared_limit_methods_filter_skips_non_matching_requests() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=2,
        per=relativedelta(minutes=1),
        scope="filtered-shared",
        methods=["GET"],
    )

    class SearchResource:
        @shared_limit
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "search"

        @shared_limit
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "search post"

    class SuggestResource:
        @shared_limit
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "suggest"

    app = falcon.App()
    app.add_route("/search", SearchResource())
    app.add_route("/suggest", SuggestResource())
    client = TestClient(app)

    assert client.post("/search").status_code == HTTP_200
    assert client.get("/search").status_code == HTTP_200
    assert client.get("/search").status_code == HTTP_200

    blocked = client.get("/suggest")

    assert blocked.status_code == HTTP_429
    assert blocked.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_shared_limit_exempt_when_skips_exempted_requests() -> None:
    key_func_calls = 0

    def key_func(req: falcon.Request) -> str:
        nonlocal key_func_calls
        key_func_calls += 1
        return "client"

    limiter = FalconRateLimiter(key_func=key_func, headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=2,
        per=relativedelta(minutes=1),
        scope="conditional-shared",
        exempt_when=lambda req: req.get_header("X-Internal") == "true",
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

    assert client.get("/search").status_code == HTTP_200
    assert client.get("/search", headers=INTERNAL_HEADERS).status_code == HTTP_200
    assert client.get("/search").status_code == HTTP_200

    blocked = client.get("/suggest")

    assert blocked.status_code == HTTP_429
    assert blocked.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
    assert key_func_calls == 3


def test_shared_limit_static_cost_consumes_shared_quota() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=5,
        per=relativedelta(minutes=1),
        scope="weighted-shared",
        cost=2,
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

    assert client.get("/search").status_code == HTTP_200
    assert client.get("/search").status_code == HTTP_200

    blocked = client.get("/suggest")

    assert blocked.status_code == HTTP_429
    assert blocked.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_shared_limit_callable_cost_consumes_dynamic_shared_quota() -> None:
    limiter = FalconRateLimiter(headers_enabled=False)
    shared_limit = limiter.shared_limit(
        requests=5,
        per=relativedelta(minutes=1),
        scope="dynamic-weighted-shared",
        cost=lambda req: int(req.get_header("X-Cost") or "1"),
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

    assert client.get("/search", headers={"X-Cost": "3"}).status_code == HTTP_200
    assert client.get("/suggest", headers={"X-Cost": "2"}).status_code == HTTP_200

    blocked = client.get("/search")

    assert blocked.status_code == HTTP_429
    assert blocked.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
