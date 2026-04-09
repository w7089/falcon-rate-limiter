import pytest
import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient
from falcon import App
from falcon.asgi import App as ASGIApp
from http import HTTPStatus

from limiter import FalconRateLimitMiddleware
from limiter.constants import (
    DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE,
    IN_MEMORY_FALLBACK_LOG_MESSAGE,
    LOGGER_NAME,
)
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


def test_memory_storage_uri_enforces_limits() -> None:
    limiter = FalconRateLimiter(storage_uri="memory://", headers_enabled=False)

    class MemoryUriResource:
        @limiter.rate_limit(requests=1, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/memory-uri", MemoryUriResource())
    client = TestClient(app)

    assert client.get("/memory-uri").status_code == HTTP_200
    assert client.get("/memory-uri").status_code == HTTP_429


def test_rate_limit_blocks_after_limit(client: TestClient) -> None:
    client.get("/test")
    client.get("/test")
    resp3 = client.get("/test")
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_class_level_rate_limit_blocks_after_limit(client: TestClient) -> None:
    resp1 = client.get("/class-test")
    resp2 = client.get("/class-test")
    resp3 = client.get("/class-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


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
    assert resp3.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_async_class_level_rate_limit_blocks_after_limit(
    async_client: TestClient,
) -> None:
    resp1 = async_client.get("/async-class-test")
    resp2 = async_client.get("/async-class-test")
    resp3 = async_client.get("/async-class-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    assert resp3.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE


def test_per_client_keys_isolate_limits(client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = client.get("/per-client", headers=headers_a)
    second_a = client.get("/per-client", headers=headers_a)
    first_b = client.get("/per-client", headers=headers_b)

    assert first_a.status_code == HTTP_200
    assert second_a.status_code == HTTP_429
    assert DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE in second_a.text
    assert first_b.status_code == HTTP_200


def test_per_client_keys_isolate_class_decorated_limits(client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = client.get("/class-per-client", headers=headers_a)
    second_a = client.get("/class-per-client", headers=headers_a)
    first_b = client.get("/class-per-client", headers=headers_b)

    assert first_a.status_code == HTTP_200
    assert second_a.status_code == HTTP_429
    assert DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE in second_a.text
    assert first_b.status_code == HTTP_200


def test_async_per_client_keys_isolate_limits(async_client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = async_client.get("/async-per-client", headers=headers_a)
    second_a = async_client.get("/async-per-client", headers=headers_a)
    first_b = async_client.get("/async-per-client", headers=headers_b)

    assert first_a.status_code == HTTP_200
    assert second_a.status_code == HTTP_429
    assert second_a.json["description"] == DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
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


def test_methods_filter_only_limits_selected_methods(client: TestClient) -> None:
    first_get = client.get("/method-filtered")
    second_get = client.get("/method-filtered")
    first_post = client.simulate_post("/method-filtered")
    second_post = client.simulate_post("/method-filtered")

    assert first_get.status_code == HTTP_200
    assert second_get.status_code == HTTP_200
    assert first_post.status_code == HTTP_200
    assert second_post.status_code == HTTP_429


def test_per_method_keeps_get_and_post_counters_separate(client: TestClient) -> None:
    first_get = client.get("/per-method")
    second_get = client.get("/per-method")
    first_post = client.simulate_post("/per-method")
    second_post = client.simulate_post("/per-method")

    assert first_get.status_code == HTTP_200
    assert second_get.status_code == HTTP_429
    assert first_post.status_code == HTTP_200
    assert second_post.status_code == HTTP_429


def test_async_methods_filter_only_limits_selected_methods(
    async_client: TestClient,
) -> None:
    first_get = async_client.get("/async-method-filtered")
    second_get = async_client.get("/async-method-filtered")
    first_post = async_client.simulate_post("/async-method-filtered")
    second_post = async_client.simulate_post("/async-method-filtered")

    assert first_get.status_code == HTTP_200
    assert second_get.status_code == HTTP_200
    assert first_post.status_code == HTTP_200
    assert second_post.status_code == HTTP_429


def test_async_per_method_keeps_get_and_post_counters_separate(
    async_client: TestClient,
) -> None:
    first_get = async_client.get("/async-per-method")
    second_get = async_client.get("/async-per-method")
    first_post = async_client.simulate_post("/async-per-method")
    second_post = async_client.simulate_post("/async-per-method")

    assert first_get.status_code == HTTP_200
    assert second_get.status_code == HTTP_429
    assert first_post.status_code == HTTP_200
    assert second_post.status_code == HTTP_429


def test_exempt_when_skips_decorated_limits(client: TestClient) -> None:
    internal_headers = {"X-Internal": "true"}

    assert (
        client.get("/conditional-exempt", headers=internal_headers).status_code
        == HTTP_200
    )
    assert (
        client.get("/conditional-exempt", headers=internal_headers).status_code
        == HTTP_200
    )

    assert client.get("/conditional-exempt").status_code == HTTP_200
    assert client.get("/conditional-exempt").status_code == HTTP_429


def test_async_exempt_when_skips_decorated_limits(async_client: TestClient) -> None:
    internal_headers = {"X-Internal": "true"}

    assert (
        async_client.get(
            "/async-conditional-exempt", headers=internal_headers
        ).status_code
        == HTTP_200
    )
    assert (
        async_client.get(
            "/async-conditional-exempt", headers=internal_headers
        ).status_code
        == HTTP_200
    )

    assert async_client.get("/async-conditional-exempt").status_code == HTTP_200
    assert async_client.get("/async-conditional-exempt").status_code == HTTP_429


def test_exempt_when_skips_middleware_limits() -> None:
    limiter = FalconRateLimiter()
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=1,
        per=relativedelta(seconds=1),
        exempt_when=lambda req: req.get_header("X-Internal") == "true",
    )

    class MiddlewareConditionalExemptResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App(middleware=[middleware])
    app.add_route(
        "/middleware-conditional-exempt", MiddlewareConditionalExemptResource()
    )
    client = TestClient(app)

    internal_headers = {"X-Internal": "true"}
    assert (
        client.get(
            "/middleware-conditional-exempt", headers=internal_headers
        ).status_code
        == HTTP_200
    )
    assert (
        client.get(
            "/middleware-conditional-exempt", headers=internal_headers
        ).status_code
        == HTTP_200
    )
    assert client.get("/middleware-conditional-exempt").status_code == HTTP_200
    assert client.get("/middleware-conditional-exempt").status_code == HTTP_429


def test_static_cost_consumes_multiple_hits(client: TestClient) -> None:
    assert client.get("/static-cost").status_code == HTTP_200
    assert client.get("/static-cost").status_code == HTTP_429


def test_dynamic_cost_uses_request_data(client: TestClient) -> None:
    weighted_headers = {"X-Request-Cost": "2"}

    assert client.get("/dynamic-cost").status_code == HTTP_200
    assert client.get("/dynamic-cost", headers=weighted_headers).status_code == HTTP_200
    assert client.get("/dynamic-cost").status_code == HTTP_429


def test_async_static_cost_consumes_multiple_hits(async_client: TestClient) -> None:
    assert async_client.get("/async-static-cost").status_code == HTTP_200
    assert async_client.get("/async-static-cost").status_code == HTTP_429


def test_async_dynamic_cost_uses_request_data(async_client: TestClient) -> None:
    weighted_headers = {"X-Request-Cost": "2"}

    assert async_client.get("/async-dynamic-cost").status_code == HTTP_200
    assert (
        async_client.get("/async-dynamic-cost", headers=weighted_headers).status_code
        == HTTP_200
    )
    assert async_client.get("/async-dynamic-cost").status_code == HTTP_429


def test_cost_applies_to_middleware_limits() -> None:
    limiter = FalconRateLimiter()
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=3,
        per=relativedelta(seconds=1),
        cost=2,
    )

    class MiddlewareCostResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App(middleware=[middleware])
    app.add_route("/middleware-cost", MiddlewareCostResource())
    client = TestClient(app)

    assert client.get("/middleware-cost").status_code == HTTP_200
    assert client.get("/middleware-cost").status_code == HTTP_429


def test_shared_limit_uses_one_bucket_across_routes(client: TestClient) -> None:
    assert client.get("/shared-first").status_code == HTTP_200
    assert client.get("/shared-second").status_code == HTTP_200
    assert client.get("/shared-first").status_code == HTTP_429


def test_async_shared_limit_uses_one_bucket_across_routes(
    async_client: TestClient,
) -> None:
    assert async_client.get("/async-shared-first").status_code == HTTP_200
    assert async_client.get("/async-shared-second").status_code == HTTP_200
    assert async_client.get("/async-shared-first").status_code == HTTP_429


def test_exempt_decorator_skips_explicit_limits(client: TestClient) -> None:
    resp1 = client.get("/exempt-decorated")
    resp2 = client.get("/exempt-decorated")
    resp3 = client.get("/exempt-decorated")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_200


def test_async_exempt_decorator_skips_explicit_limits(
    async_client: TestClient,
) -> None:
    resp1 = async_client.get("/async-exempt-decorated")
    resp2 = async_client.get("/async-exempt-decorated")
    resp3 = async_client.get("/async-exempt-decorated")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_200


def test_exempt_decorator_supports_resource_instances() -> None:
    limiter = FalconRateLimiter()

    class SharedResource:
        @limiter.rate_limit(requests=1, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    exempt_resource = SharedResource()
    limited_resource = SharedResource()
    limiter.exempt(exempt_resource)

    app = falcon.App()
    app.add_route("/instance-exempt", exempt_resource)
    app.add_route("/instance-limited", limited_resource)
    client = TestClient(app)

    assert client.get("/instance-exempt").status_code == HTTP_200
    assert client.get("/instance-exempt").status_code == HTTP_200
    assert client.get("/instance-exempt").status_code == HTTP_200

    assert client.get("/instance-limited").status_code == HTTP_200
    assert client.get("/instance-limited").status_code == HTTP_429


def test_unavailable_storage_uri_falls_back_to_memory(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = FalconRateLimiter(
        storage_uri="redis://localhost:6399/0",
        headers_enabled=False,
    )

    class FallbackResource:
        @limiter.rate_limit(requests=1, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/fallback", FallbackResource())
    client = TestClient(app)

    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        assert client.get("/fallback").status_code == HTTP_200
        assert client.get("/fallback").status_code == HTTP_429

    assert IN_MEMORY_FALLBACK_LOG_MESSAGE in caplog.text


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


# --- Native async vs thread-pool fallback ---


def test_native_async_path_does_not_use_to_thread(
    async_client: TestClient,
) -> None:
    """When async support is active, asyncio.to_thread should not be called."""
    from unittest.mock import patch

    with patch("limiter._helpers.asyncio.to_thread") as mock_to_thread:
        resp1 = async_client.get("/async-test")
        resp2 = async_client.get("/async-test")
        resp3 = async_client.get("/async-test")

    assert resp1.status_code == HTTP_200
    assert resp2.status_code == HTTP_200
    assert resp3.status_code == HTTP_429
    mock_to_thread.assert_not_called()


def test_thread_pool_fallback_when_explicit_storage() -> None:
    """When an explicit Storage instance is passed, async falls back to to_thread."""
    from unittest.mock import AsyncMock, patch
    from limits.storage import MemoryStorage

    limiter = FalconRateLimiter(storage=MemoryStorage())
    assert limiter._storage_controller.has_async_support is False

    class AsyncResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.asgi.App()
    app.add_route("/thread-fallback", AsyncResource())
    client = TestClient(app)

    with patch(
        "limiter._helpers.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.return_value = (True, None)
        resp = client.get("/thread-fallback")

    assert resp.status_code == HTTP_200
    mock_to_thread.assert_called()
