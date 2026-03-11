import pytest
import falcon
from dateutil.relativedelta import relativedelta
from limiter.core import FalconRateLimiter

@pytest.fixture
def limiter():
    return FalconRateLimiter()

@pytest.fixture
def falcon_app(limiter):
    class TestResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        def on_get(self, req, resp):
            resp.status = falcon.HTTP_200
            resp.text = "OK"
    app = falcon.App()
    app.add_route("/test", TestResource())
    return app

@pytest.fixture
def client(falcon_app):
    from falcon.testing import TestClient
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
