from collections.abc import Callable
from http import HTTPStatus

import falcon
import falcon.asgi
import pytest
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient

from limiter.core import FalconRateLimiter

HTTP_200 = HTTPStatus.OK
HTTP_429 = HTTPStatus.TOO_MANY_REQUESTS
HTTP_500 = HTTPStatus.INTERNAL_SERVER_ERROR
INTERNAL_HEADERS = {"X-Internal": "true"}


def _is_internal_request(req: falcon.Request) -> bool:
    return req.get_header("X-Internal") == "true"


def _is_never_exempt(req: falcon.Request) -> bool:
    return False


def _broken_exemption(req: falcon.Request) -> bool:
    if req.get_header("X-Internal") == "true":
        raise RuntimeError("broken exemption")
    return False


@pytest.mark.parametrize(
    ("exempt_when", "expected_status", "expected_key_func_calls"),
    [
        pytest.param(_is_internal_request, HTTP_200, 1, id="exempt"),
        pytest.param(_is_never_exempt, HTTP_429, 2, id="not-exempt"),
        pytest.param(_broken_exemption, HTTP_500, 1, id="exception"),
    ],
)
def test_sync_exempt_when_behavior(
    exempt_when: Callable[[falcon.Request], bool],
    expected_status: HTTPStatus,
    expected_key_func_calls: int,
) -> None:
    key_func_calls = 0

    def key_func(req: falcon.Request) -> str:
        nonlocal key_func_calls
        key_func_calls += 1
        return "client"

    limiter = FalconRateLimiter(key_func=key_func)

    @limiter.rate_limit(
        requests=1,
        per=relativedelta(seconds=1),
        exempt_when=exempt_when,
    )
    class ConditionalExemptionResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/conditional-exemption", ConditionalExemptionResource())
    client = TestClient(app)

    assert client.get("/conditional-exemption").status_code == HTTP_200

    resp = client.get("/conditional-exemption", headers=INTERNAL_HEADERS)

    assert resp.status_code == expected_status
    assert key_func_calls == expected_key_func_calls


@pytest.mark.parametrize(
    ("exempt_when", "expected_status", "expected_key_func_calls"),
    [
        pytest.param(_is_internal_request, HTTP_200, 1, id="exempt"),
        pytest.param(_is_never_exempt, HTTP_429, 2, id="not-exempt"),
        pytest.param(_broken_exemption, HTTP_500, 1, id="exception"),
    ],
)
def test_async_exempt_when_behavior(
    exempt_when: Callable[[falcon.Request], bool],
    expected_status: HTTPStatus,
    expected_key_func_calls: int,
) -> None:
    key_func_calls = 0

    def key_func(req: falcon.Request) -> str:
        nonlocal key_func_calls
        key_func_calls += 1
        return "client"

    limiter = FalconRateLimiter(key_func=key_func)

    @limiter.rate_limit(
        requests=1,
        per=relativedelta(seconds=1),
        exempt_when=exempt_when,
    )
    class AsyncConditionalExemptionResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.asgi.App()
    app.add_route("/async-conditional-exemption", AsyncConditionalExemptionResource())
    client = TestClient(app)

    assert client.get("/async-conditional-exemption").status_code == HTTP_200

    resp = client.get("/async-conditional-exemption", headers=INTERNAL_HEADERS)

    assert resp.status_code == expected_status
    assert key_func_calls == expected_key_func_calls
