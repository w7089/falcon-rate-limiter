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
- Falcon middleware-based automatic checks for undecorated routes

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

## Design notes

- limits are backed by `limits.FixedWindowRateLimiter`
- in-memory storage is used by default
- rejected requests raise `falcon.HTTPTooManyRequests`
- middleware currently takes explicit `requests` and `per` arguments
- automatic default limits for all routes are planned separately in Phase 3.2
