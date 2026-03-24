from collections.abc import Generator

import httpx
import pytest

BASE_URL = "http://localhost:8765"


@pytest.fixture(scope="session", autouse=True)
def require_app_running() -> Generator[None, None, None]:
    """Skip the entire e2e suite if the app is not already running.

    Start the stack with 'make e2e-up' before running these tests.
    """
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=3)
        resp.raise_for_status()
    except Exception:
        pytest.skip("E2E app is not running — start it with 'make e2e-up'")
    yield


@pytest.fixture
def http() -> Generator[httpx.Client, None, None]:
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        yield client
