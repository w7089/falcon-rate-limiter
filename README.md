# Falcon Rate Limiter

`falcon-rate-limiter` adds request rate limiting to Falcon applications using the
[`limits`](https://limits.readthedocs.io/) library.

Current implemented features include:

- decorator-based rate limiting for Falcon responders
- class-level rate limiting for Falcon resources
- sync and async (ASGI) responder support
- per-client keys via `key_func`
- `429 Too Many Requests` errors via `falcon.HTTPTooManyRequests`
- rate-limit response headers
- URI-configured storage backends via `limits` (including Redis)
- Falcon middleware-based automatic checks for undecorated routes
- `@limiter.exempt` to skip explicit and default limits
- in-memory fallback with recovery probing when primary storage is unavailable

## Installation

```bash
uv add falcon-rate-limiter
```

## Quick start

Use `FalconRateLimiter` when you want explicit, per-route decorators.

```python
import falcon
from dateutil.relativedelta import relativedelta

from limiter import FalconRateLimiter

limiter = FalconRateLimiter()


class HelloResource:
    @limiter.rate_limit(requests=5, per=relativedelta(minutes=1))
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "hello"


app = falcon.App()
app.add_route("/hello", HelloResource())
```

After the fifth request within one minute, Falcon raises
`falcon.HTTPTooManyRequests` and returns a `429` response.

## Decorator usage

You can decorate individual responders:

```python
class SearchResource:
    @limiter.rate_limit(requests=10, per=relativedelta(minutes=1))
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"items": []}
```

You can also limit only selected HTTP methods:

```python
class ReportResource:
    @limiter.rate_limit(
        requests=5,
        per=relativedelta(minutes=1),
        methods=["POST"],
    )
    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "queued"
```

Use `per_method=True` when different HTTP methods can reach the same responder
and should keep separate counters. This is especially useful for Falcon's
implicit `HEAD` handling on `on_get` responders:

```python
class StatusResource:
    @limiter.rate_limit(
        requests=10,
        per=relativedelta(minutes=1),
        per_method=True,
    )
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "ok"
```

Or decorate an entire resource class:

```python
@limiter.rate_limit(requests=20, per=relativedelta(minutes=1))
class ArticleResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "article list"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "created"
```

Class decoration applies the same limit wrapper to all methods whose names start
with `on_`.

## Custom error messages

You can override the default `"Rate limit exceeded"` message:

```python
class LoginResource:
    @limiter.rate_limit(
        requests=3,
        per=relativedelta(minutes=1),
        error_message="Too many login attempts",
    )
    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "ok"
```

## Per-client key functions

By default, the limiter uses the client address from `req.access_route`,
falling back to `req.remote_addr`, and then to `"global"`.

You can customize how clients are identified:

```python
import falcon


def client_key(req: falcon.Request) -> str:
    return req.get_header("X-Client-Id") or req.remote_addr or "global"


limiter = FalconRateLimiter(key_func=client_key)
```

You can also override the key function for a single decorator:

```python
class TenantResource:
    @limiter.rate_limit(
        requests=30,
        per=relativedelta(minutes=1),
        key_func=lambda req: req.get_header("X-Tenant-Id") or "global",
    )
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "tenant data"
```

Internally, each limit key combines the responder's `__qualname__` with the
resolved client key, so different endpoints do not share counters by accident.

## Response headers

When `headers_enabled=True` (the default), successful and rejected responses
include standard rate-limit metadata:

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`
- `Retry-After` on rejected requests

```python
limiter = FalconRateLimiter(headers_enabled=True)
```

## Storage backends

By default, the limiter uses in-memory storage:

```python
limiter = FalconRateLimiter()
```

You can also configure storage with a `limits` URI:

```python
limiter = FalconRateLimiter(storage_uri="memory://")
```

Redis-backed rate limiting uses the same constructor:

```python
limiter = FalconRateLimiter(storage_uri="redis://localhost:6379/0")
```

If you already created a `limits` storage object yourself, you can still pass
it with `storage=...`. `storage` and `storage_uri` are mutually exclusive.

### Storage resilience

When a non-memory primary storage backend is unavailable during startup or
request handling, the limiter switches to an in-memory fallback so requests can
continue to be rate limited.

While running on the fallback backend, the limiter periodically probes the
configured primary storage using exponential backoff. Once the primary storage
is healthy again, the limiter restores it automatically.

```python
limiter = FalconRateLimiter(
    storage_uri="redis://localhost:6379/0",
    recovery_backoff_seconds=1.0,
    max_recovery_backoff_seconds=30.0,
)
```

This fallback is intended for resilience, not shared consistency: while the
application is using the in-memory fallback, counters are local to that process.

## Middleware-based rate limiting

Phase 3.1 introduces `FalconRateLimitMiddleware`. This is useful when you want
rate limiting to happen automatically in Falcon middleware rather than manually
decorating every route.

```python
import falcon
from dateutil.relativedelta import relativedelta

from limiter import FalconRateLimiter, FalconRateLimitMiddleware

limiter = FalconRateLimiter()
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=100,
    per=relativedelta(minutes=1),
)


class HealthResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "ok"


app = falcon.App(middleware=[middleware])
app.add_route("/health", HealthResource())
```

In this setup, the middleware checks requests in `process_resource()` before the
responder runs.

## Default limits for undecorated routes

You can define app-wide default limits on the limiter and let middleware apply
them to routes that do not have their own `@rate_limit(...)` decorator.

```python
import falcon
from dateutil.relativedelta import relativedelta

from limiter import FalconRateLimiter, FalconRateLimitMiddleware

limiter = FalconRateLimiter(
    default_requests=10,
    default_per=relativedelta(minutes=1),
)
middleware = FalconRateLimitMiddleware(limiter)


class StatusResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "ok"


app = falcon.App(middleware=[middleware])
app.add_route("/status", StatusResource())
```

With this setup, `/status` is limited to ten requests per minute per client even
though the resource is undecorated.

### What is `limit_undecorated_routes`?

`limit_undecorated_routes` is a toggle on `FalconRateLimiter` that controls whether the
middleware should automatically enforce limits for undecorated routes.

```python
limiter = FalconRateLimiter(limit_undecorated_routes=True)   # default
```

When `limit_undecorated_routes=True`:

- middleware applies its configured limit to routes that are not decorated
- decorated responders/resources are skipped by the middleware to avoid
  double-counting

When `limit_undecorated_routes=False`:

- the middleware becomes a no-op for automatic checks
- explicitly decorated routes still enforce their own `@rate_limit(...)`
  limits, because decorators do not depend on middleware auto-checking

Example:

```python
limiter = FalconRateLimiter(limit_undecorated_routes=False)
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=10,
    per=relativedelta(minutes=1),
)

app = falcon.App(middleware=[middleware])
```

With the configuration above, undecorated routes are not limited by the
middleware.

## Exempting routes from all limiting

Use `@limiter.exempt` when a responder or resource must bypass both explicit
decorator limits and middleware-applied default limits.

```python
import falcon

from limiter import FalconRateLimiter

limiter = FalconRateLimiter()


class MetricsResource:
    @limiter.exempt
    @limiter.rate_limit(requests=1, per=relativedelta(seconds=1))
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "always available"
```

You can also exempt an entire resource class:

```python
@limiter.exempt
class HealthResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "ok"
```

Class exemption applies to every instance of that resource class registered in
the app. If you only want to exempt one mounted resource object, exempt the
instance instead:

```python
class HealthResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "ok"


public_health = HealthResource()
internal_health = HealthResource()

limiter.exempt(internal_health)

app.add_route("/health", public_health)
app.add_route("/internal/health", internal_health)
```

With this setup, only `/internal/health` is exempt. `/health` still uses the
configured limits.

### Mixing middleware with decorators

Middleware and decorators are designed to work together safely.

```python
limiter = FalconRateLimiter()
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=100,
    per=relativedelta(minutes=1),
)


class PublicResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "public"


class LoginResource:
    @limiter.rate_limit(requests=5, per=relativedelta(minutes=1))
    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "logged in"


app = falcon.App(middleware=[middleware])
app.add_route("/public", PublicResource())
app.add_route("/login", LoginResource())
```

Behavior:

- `/public` is limited by middleware
- `/login` is limited by the decorator
- middleware detects the decorated responder and skips it, so the request is
  checked only once

## ASGI / async responders

Async Falcon responders are supported. The underlying synchronous `limits`
operations are executed in a worker thread so the event loop is not blocked.

```python
import falcon.asgi

from limiter import FalconRateLimiter, FalconRateLimitMiddleware

limiter = FalconRateLimiter()
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=25,
    per=relativedelta(minutes=1),
)


class AsyncResource:
    @limiter.rate_limit(requests=5, per=relativedelta(seconds=30))
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"status": "ok"}


app = falcon.asgi.App(middleware=[middleware])
app.add_route("/async", AsyncResource())
```

## Development and releases

- Versions follow [Semantic Versioning](https://semver.org/).
- Pull requests and pushes to `main` run the GitHub Actions CI workflow.
- Creating a `vX.Y.Z` tag publishes the matching `pyproject.toml` version to PyPI.
- Dependabot keeps `uv` dependencies and GitHub Actions versions up to date.

## Design notes

- limits are backed by `limits.FixedWindowRateLimiter`
- in-memory storage is used by default
- rejected requests raise `falcon.HTTPTooManyRequests`
- middleware can use explicit limits or the limiter's default limit
- `@limiter.exempt` bypasses both decorator and middleware-based checks
