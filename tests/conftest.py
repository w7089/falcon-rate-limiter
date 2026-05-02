import asyncio

import pytest
from falcon.asgi import App as ASGIApp
from falcon import App
from falcon.testing import TestClient

from limiter.core import FalconRateLimiter
from tests.test_app import (
    create_app,
    create_async_app,
    create_async_middleware_app,
    create_middleware_app,
)


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


@pytest.fixture
def middleware_client() -> TestClient:
    return TestClient(create_middleware_app())


@pytest.fixture
def async_middleware_client() -> TestClient:
    return TestClient(create_async_middleware_app())


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        yield loop
    finally:
        loop.close()
        asyncio.set_event_loop(None)
