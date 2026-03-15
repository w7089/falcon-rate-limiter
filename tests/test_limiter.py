import pytest
from falcon.testing import TestClient

from limiter.core import FalconRateLimiter
from tests.test_app import create_app, create_async_app


@pytest.fixture
def limiter():
    return FalconRateLimiter()

@pytest.fixture
def falcon_app():
    return create_app()

@pytest.fixture
def client(falcon_app):
    return TestClient(falcon_app)


@pytest.fixture
def async_falcon_app():
    return create_async_app()


@pytest.fixture
def async_client(async_falcon_app):
    return TestClient(async_falcon_app)

def test_rate_limit_allows_requests(client):
    resp1 = client.get("/test")
    resp2 = client.get("/test")
    assert resp1.status_code == 200
    assert resp2.status_code == 200

def test_rate_limit_blocks_after_limit(client):
    client.get("/test")
    client.get("/test")
    resp3 = client.get("/test")
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_class_level_rate_limit_blocks_after_limit(client):
    resp1 = client.get("/class-test")
    resp2 = client.get("/class-test")
    resp3 = client.get("/class-test")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_async_rate_limit_allows_requests(async_client):
    resp1 = async_client.get("/async-test")
    resp2 = async_client.get("/async-test")

    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_async_rate_limit_blocks_after_limit(async_client):
    async_client.get("/async-test")
    async_client.get("/async-test")
    resp3 = async_client.get("/async-test")

    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_async_class_level_rate_limit_blocks_after_limit(async_client):
    resp1 = async_client.get("/async-class-test")
    resp2 = async_client.get("/async-class-test")
    resp3 = async_client.get("/async-class-test")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text
