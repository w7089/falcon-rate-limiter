import pytest
from falcon.testing import TestClient
from falcon import App
from falcon.asgi import App as ASGIApp

from limiter.core import FalconRateLimiter
from tests.test_app import create_app, create_async_app


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


def test_rate_limit_allows_requests(client: TestClient) -> None:
    resp1 = client.get("/test")
    resp2 = client.get("/test")
    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_rate_limit_blocks_after_limit(client: TestClient) -> None:
    client.get("/test")
    client.get("/test")
    resp3 = client.get("/test")
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_class_level_rate_limit_blocks_after_limit(client: TestClient) -> None:
    resp1 = client.get("/class-test")
    resp2 = client.get("/class-test")
    resp3 = client.get("/class-test")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_async_rate_limit_allows_requests(async_client: TestClient) -> None:
    resp1 = async_client.get("/async-test")
    resp2 = async_client.get("/async-test")

    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_async_rate_limit_blocks_after_limit(async_client: TestClient) -> None:
    async_client.get("/async-test")
    async_client.get("/async-test")
    resp3 = async_client.get("/async-test")

    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_async_class_level_rate_limit_blocks_after_limit(
    async_client: TestClient,
) -> None:
    resp1 = async_client.get("/async-class-test")
    resp2 = async_client.get("/async-class-test")
    resp3 = async_client.get("/async-class-test")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_per_client_keys_isolate_limits(client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = client.get("/per-client", headers=headers_a)
    second_a = client.get("/per-client", headers=headers_a)
    first_b = client.get("/per-client", headers=headers_b)

    assert first_a.status_code == 200
    assert second_a.status_code == 429
    assert "Rate limit exceeded" in second_a.text
    assert first_b.status_code == 200


def test_per_client_keys_isolate_class_decorated_limits(client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = client.get("/class-per-client", headers=headers_a)
    second_a = client.get("/class-per-client", headers=headers_a)
    first_b = client.get("/class-per-client", headers=headers_b)

    assert first_a.status_code == 200
    assert second_a.status_code == 429
    assert "Rate limit exceeded" in second_a.text
    assert first_b.status_code == 200


def test_async_per_client_keys_isolate_limits(async_client: TestClient) -> None:
    headers_a = {"X-Client-Id": "client-a"}
    headers_b = {"X-Client-Id": "client-b"}

    first_a = async_client.get("/async-per-client", headers=headers_a)
    second_a = async_client.get("/async-per-client", headers=headers_a)
    first_b = async_client.get("/async-per-client", headers=headers_b)

    assert first_a.status_code == 200
    assert second_a.status_code == 429
    assert "Rate limit exceeded" in second_a.text
    assert first_b.status_code == 200
