"""
End-to-end tests for falcon-rate-limiter.

Each test generates a unique X-Test-Client-Id so rate-limit counters
are fully isolated — tests never share state even within the same run.
"""

import uuid

import httpx


def _uid() -> str:
    return str(uuid.uuid4())


def test_health(http: httpx.Client) -> None:
    resp = http.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_allowed_requests_return_200(http: httpx.Client) -> None:
    client_id = _uid()
    headers = {"X-Test-Client-Id": client_id}
    for _ in range(3):
        resp = http.get("/limited", headers=headers)
        assert resp.status_code == 200


def test_request_beyond_limit_returns_429(http: httpx.Client) -> None:
    client_id = _uid()
    headers = {"X-Test-Client-Id": client_id}
    for _ in range(3):
        http.get("/limited", headers=headers)
    resp = http.get("/limited", headers=headers)
    assert resp.status_code == 429
    body = resp.json()
    assert body["description"] == "Rate limit exceeded"


def test_x_ratelimit_headers_present_on_allowed(http: httpx.Client) -> None:
    client_id = _uid()
    headers = {"X-Test-Client-Id": client_id}
    resp = http.get("/headers", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Reset" in resp.headers


def test_x_ratelimit_remaining_decrements(http: httpx.Client) -> None:
    client_id = _uid()
    headers = {"X-Test-Client-Id": client_id}
    resp1 = http.get("/headers", headers=headers)
    resp2 = http.get("/headers", headers=headers)
    assert resp1.headers["X-RateLimit-Remaining"] == "1"
    assert resp2.headers["X-RateLimit-Remaining"] == "0"


def test_retry_after_header_on_429(http: httpx.Client) -> None:
    client_id = _uid()
    headers = {"X-Test-Client-Id": client_id}
    http.get("/headers", headers=headers)
    http.get("/headers", headers=headers)
    resp = http.get("/headers", headers=headers)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


def test_x_ratelimit_headers_present_on_429(http: httpx.Client) -> None:
    client_id = _uid()
    headers = {"X-Test-Client-Id": client_id}
    http.get("/headers", headers=headers)
    http.get("/headers", headers=headers)
    resp = http.get("/headers", headers=headers)
    assert resp.status_code == 429
    assert resp.headers["X-RateLimit-Limit"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in resp.headers


def test_custom_error_message(http: httpx.Client) -> None:
    client_id = _uid()
    headers = {"X-Test-Client-Id": client_id}
    http.get("/custom-error", headers=headers)
    resp = http.get("/custom-error", headers=headers)
    assert resp.status_code == 429
    assert resp.json()["description"] == "slow down, please"


def test_different_clients_have_independent_counters(http: httpx.Client) -> None:
    id_a, id_b = _uid(), _uid()
    for _ in range(3):
        http.get("/limited", headers={"X-Test-Client-Id": id_a})
    blocked = http.get("/limited", headers={"X-Test-Client-Id": id_a})
    still_allowed = http.get("/limited", headers={"X-Test-Client-Id": id_b})
    assert blocked.status_code == 429
    assert still_allowed.status_code == 200


def test_default_limits_apply_to_undecorated_routes(http: httpx.Client) -> None:
    headers = {"X-Test-Client-Id": _uid()}
    first = http.get("/default-limited", headers=headers)
    second = http.get("/default-limited", headers=headers)
    third = http.get("/default-limited", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
