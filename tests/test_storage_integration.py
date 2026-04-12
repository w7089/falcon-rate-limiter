import pytest
import falcon
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient
from http import HTTPStatus

from limiter.constants import IN_MEMORY_FALLBACK_LOG_MESSAGE
from limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS


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

    with caplog.at_level("WARNING", logger="falcon-rate-limiter"):
        assert client.get("/fallback").status_code == HTTP_200
        assert client.get("/fallback").status_code == HTTP_429

    assert IN_MEMORY_FALLBACK_LOG_MESSAGE in caplog.text
