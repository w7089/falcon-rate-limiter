import falcon
import pytest
from dateutil.relativedelta import relativedelta
from falcon import testing
from typing import Any, cast

from limiter import FalconRateLimitMiddleware, FalconRateLimiter
from limiter.utils import _get_remote_address


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


def test_limiter_constructor_optional_config_is_keyword_only() -> None:
    # Bypass static signature checks so pytest can assert the runtime TypeError.
    limiter_class = cast(Any, FalconRateLimiter)

    with pytest.raises(TypeError):
        limiter_class(None)


def test_rate_limit_optional_config_is_keyword_only() -> None:
    limiter = FalconRateLimiter()
    # Bypass static signature checks so pytest can assert the runtime TypeError.
    rate_limit = cast(Any, limiter.rate_limit)

    with pytest.raises(TypeError):
        rate_limit(1, relativedelta(seconds=1), None)


def test_create_limit_optional_config_is_keyword_only() -> None:
    limiter = FalconRateLimiter()
    # Bypass static signature checks so pytest can assert the runtime TypeError.
    create_limit = cast(Any, limiter.create_limit)

    with pytest.raises(TypeError):
        create_limit(1, relativedelta(seconds=1), None)


def test_middleware_optional_config_is_keyword_only() -> None:
    limiter = FalconRateLimiter()
    # Bypass static signature checks so pytest can assert the runtime TypeError.
    middleware_class = cast(Any, FalconRateLimitMiddleware)

    with pytest.raises(TypeError):
        middleware_class(limiter, 1, relativedelta(seconds=1))
