import falcon
from falcon import testing

from limiter import FalconRateLimiter
from limiter.core import _get_remote_address


def test_default_key_uses_forwarded_address() -> None:
    limiter = FalconRateLimiter()

    key_func = limiter._resolve_key_func(None)
    req_a = falcon.Request(
        testing.create_environ(
            path="/",
            headers={"X-Forwarded-For": "10.0.0.1, 10.0.0.2"},
            remote_addr="127.0.0.1",
        )
    )
    req_b = falcon.Request(
        testing.create_environ(
            path="/",
            headers={"X-Forwarded-For": "10.0.0.3, 10.0.0.4"},
            remote_addr="127.0.0.1",
        )
    )

    assert key_func(req_a) == "10.0.0.1"
    assert key_func(req_b) == "10.0.0.3"


def test_get_remote_address_falls_back_to_remote_addr() -> None:
    req = falcon.Request(testing.create_environ(path="/", remote_addr="127.0.0.1"))
    assert _get_remote_address(req) == "127.0.0.1"
