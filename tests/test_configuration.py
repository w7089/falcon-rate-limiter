import falcon
import pytest
from dateutil.relativedelta import relativedelta
from falcon.testing import TestClient

from limiter import FalconRateLimitMiddleware, FalconRateLimiter
from limiter._config import load_environment_config
from limiter.constants import (
    LOGGER_NAME,
    RATELIMIT_ENABLED_ENV,
    RATELIMIT_HEADERS_ENABLED_ENV,
    RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV,
    RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV,
    RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV,
    RATELIMIT_STORAGE_URL_ENV,
    RATELIMIT_SWALLOW_ERRORS_ENV,
    RATE_LIMIT_EXCEEDED_LOG_MESSAGE,
    SWALLOWED_RATE_LIMIT_ERROR_LOG_MESSAGE,
)


def test_enabled_false_skips_decorated_limits() -> None:
    limiter = FalconRateLimiter(enabled=False)

    class DisabledResource:
        @limiter.rate_limit(requests=1, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/disabled", DisabledResource())
    client = TestClient(app)

    assert client.get("/disabled").status_code == 200
    assert client.get("/disabled").status_code == 200
    assert client.get("/disabled").status_code == 200


def test_enabled_false_skips_middleware_limits() -> None:
    limiter = FalconRateLimiter(enabled=False)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=1,
        per=relativedelta(seconds=1),
    )

    class DisabledMiddlewareResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App(middleware=[middleware])
    app.add_route("/disabled-middleware", DisabledMiddlewareResource())
    client = TestClient(app)

    assert client.get("/disabled-middleware").status_code == 200
    assert client.get("/disabled-middleware").status_code == 200
    assert client.get("/disabled-middleware").status_code == 200


def test_environment_config_reads_limiter_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RATELIMIT_ENABLED_ENV, "false")
    monkeypatch.setenv(RATELIMIT_HEADERS_ENABLED_ENV, "false")
    monkeypatch.setenv(RATELIMIT_STORAGE_URL_ENV, "memory://")
    monkeypatch.setenv(RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV, "false")
    monkeypatch.setenv(RATELIMIT_SWALLOW_ERRORS_ENV, "true")
    monkeypatch.setenv(RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV, "2.5")
    monkeypatch.setenv(RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV, "5.5")

    limiter = FalconRateLimiter()

    assert limiter.enabled is False
    assert limiter.limit_undecorated_routes is False
    assert limiter._headers_enabled is False
    assert limiter._swallow_errors is True
    assert limiter._storage_controller._recovery_backoff_seconds == 2.5
    assert limiter._storage_controller._max_recovery_backoff_seconds == 5.5


def test_constructor_overrides_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RATELIMIT_ENABLED_ENV, "false")
    monkeypatch.setenv(RATELIMIT_HEADERS_ENABLED_ENV, "false")
    monkeypatch.setenv(RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV, "false")
    monkeypatch.setenv(RATELIMIT_SWALLOW_ERRORS_ENV, "true")
    monkeypatch.setenv(RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV, "2.5")
    monkeypatch.setenv(RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV, "5.5")

    limiter = FalconRateLimiter(
        enabled=True,
        headers_enabled=True,
        limit_undecorated_routes=True,
        swallow_errors=False,
        recovery_backoff_seconds=1.5,
        max_recovery_backoff_seconds=3.0,
    )

    assert limiter.enabled is True
    assert limiter.limit_undecorated_routes is True
    assert limiter._headers_enabled is True
    assert limiter._swallow_errors is False
    assert limiter._storage_controller._recovery_backoff_seconds == 1.5
    assert limiter._storage_controller._max_recovery_backoff_seconds == 3.0


@pytest.mark.parametrize(
    ("env_name", "value", "message"),
    [
        (RATELIMIT_ENABLED_ENV, "maybe", "must be one of"),
        (RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV, "soon", "must be a float"),
    ],
)
def test_invalid_environment_values_raise_value_error(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(env_name, value)

    with pytest.raises(ValueError, match=message):
        load_environment_config()


def test_explicit_constructor_override_ignores_invalid_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RATELIMIT_ENABLED_ENV, "maybe")

    limiter = FalconRateLimiter(enabled=True)

    assert limiter.enabled is True


def test_rate_limit_exceeded_logs_with_dedicated_logger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = FalconRateLimiter()

    class LoggedResource:
        @limiter.rate_limit(requests=1, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/logged", LoggedResource())
    client = TestClient(app)

    client.get("/logged")
    with caplog.at_level("INFO", logger=LOGGER_NAME):
        assert client.get("/logged").status_code == 429

    assert RATE_LIMIT_EXCEEDED_LOG_MESSAGE in caplog.text


def test_swallow_errors_allows_sync_request_to_continue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = FalconRateLimiter(swallow_errors=True)

    class SwallowSyncResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            cost=lambda req: 0,
        )
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App()
    app.add_route("/swallow-sync", SwallowSyncResource())
    client = TestClient(app)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        assert client.get("/swallow-sync").status_code == 200

    assert SWALLOWED_RATE_LIMIT_ERROR_LOG_MESSAGE in caplog.text


def test_swallow_errors_allows_async_request_to_continue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = FalconRateLimiter(swallow_errors=True)

    class SwallowAsyncResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            cost=lambda req: 0,
        )
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.asgi.App()
    app.add_route("/swallow-async", SwallowAsyncResource())
    client = TestClient(app)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        assert client.get("/swallow-async").status_code == 200

    assert SWALLOWED_RATE_LIMIT_ERROR_LOG_MESSAGE in caplog.text


def test_swallow_errors_allows_middleware_request_to_continue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = FalconRateLimiter(swallow_errors=True)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=1,
        per=relativedelta(seconds=1),
        cost=lambda req: 0,
    )

    class SwallowMiddlewareResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.text = "ok"

    app = falcon.App(middleware=[middleware])
    app.add_route("/swallow-middleware", SwallowMiddlewareResource())
    client = TestClient(app)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        assert client.get("/swallow-middleware").status_code == 200

    assert SWALLOWED_RATE_LIMIT_ERROR_LOG_MESSAGE in caplog.text


def test_swallow_errors_does_not_hide_invalid_static_configuration() -> None:
    limiter = FalconRateLimiter(swallow_errors=True)

    with pytest.raises(ValueError, match="positive integer"):

        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            cost=0,
        )
        def invalid_resource(
            req: falcon.Request,
            resp: falcon.Response,
        ) -> None:
            resp.text = "ok"

        del invalid_resource
