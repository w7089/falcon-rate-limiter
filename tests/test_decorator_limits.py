import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient
from http import HTTPStatus

from limiter.constants import DEFAULT_RATE_LIMIT_EXCEEDED_MESSAGE
from limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


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
