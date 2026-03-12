import pytest
from falcon.testing import TestClient

from limiter.core import FalconRateLimiter
from tests.test_app import create_app


@pytest.fixture
def limiter():
    return FalconRateLimiter()

@pytest.fixture
def falcon_app():
    return create_app()

@pytest.fixture
def client(falcon_app):
    return TestClient(falcon_app)

def test_rate_limit_allows_requests(client):
    resp1 = client.simulate_get("/test")
    resp2 = client.simulate_get("/test")
    assert resp1.status_code == 200
    assert resp2.status_code == 200

def test_rate_limit_blocks_after_limit(client):
    client.simulate_get("/test")
    client.simulate_get("/test")
    resp3 = client.simulate_get("/test")
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text


def test_class_level_rate_limit_blocks_after_limit(client):
    resp1 = client.simulate_get("/class-test")
    resp2 = client.simulate_get("/class-test")
    resp3 = client.simulate_get("/class-test")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429
    assert "Rate limit exceeded" in resp3.text
