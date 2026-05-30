# Falcon Rate Limiter

`falcon-rate-limiter` adds request rate limiting to Falcon applications using the
[`limits`](https://limits.readthedocs.io/) library.

Current implemented features include:

- decorator-based rate limiting for Falcon responders
- class-level rate limiting for Falcon resources
- shared limits across multiple responders or resources
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

## Shared limits

Use `shared_limit()` when multiple responders or resources should consume quota
from the same bucket.

```python
shared_api_limit = limiter.shared_limit(
    requests=5,
    per=relativedelta(minutes=1),
    scope="api-v1",
)


class SearchResource:
    @shared_api_limit
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "search"


class SuggestResource:
    @shared_api_limit
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "suggest"
```

With this setup, requests to `/search` and `/suggest` spend from the same
`api-v1` bucket for a given client key.

You can also apply one shared decorator to a resource class:

```python
shared_write_limit = limiter.shared_limit(
    requests=10,
    per=relativedelta(minutes=1),
    scope="writes",
    per_method=True,
)


@shared_write_limit
class ArticleResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "list"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "created"
```

When `per_method=True`, the shared scope still separates counters by HTTP
method, so `GET` and `POST` do not consume the same bucket.

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

## Method filters and per-method limits

Use `methods` when a limit should apply only to specific HTTP methods:

```python
class SearchResource:
    @limiter.rate_limit(
        requests=5,
        per=relativedelta(minutes=1),
        methods=["GET"],
    )
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = {"items": []}
```

Requests whose method is not listed are skipped by that limit and do not consume
quota.

Use `per_method=True` when one configured limit should keep separate counters
for each HTTP method:

```python
class UploadResource:
    @limiter.rate_limit(
        requests=10,
        per=relativedelta(minutes=1),
        per_method=True,
    )
    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "uploaded"
```

`per_method=True` is also supported by `FalconRateLimitMiddleware`:

```python
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=100,
    per=relativedelta(minutes=1),
    per_method=True,
)
```

With the default responder scope, methods such as `on_get` and `on_post` often
already have separate counters. `per_method=True` is most useful when a shared
or manually chosen scope would otherwise group multiple HTTP methods together.

## Weighted requests

Use `cost` when one request should consume more than one quota unit.

```python
class ReportResource:
    @limiter.rate_limit(
        requests=50,
        per=relativedelta(minutes=1),
        cost=10,
    )
    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "created"
```

In this example, each accepted request consumes ten quota units from the
`50/minute` limit.

`cost` can also be a callable that derives quota units from the current request:

```python
class BatchResource:
    @limiter.rate_limit(
        requests=100,
        per=relativedelta(minutes=1),
        cost=lambda req: int(req.get_header("X-Batch-Size") or "1"),
    )
    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "accepted"
```

Requests skipped by `methods=[...]` or `exempt_when` do not resolve cost and do
not consume quota for that limit.

`cost` is also supported by explicit middleware limits:

```python
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=100,
    per=relativedelta(minutes=1),
    cost=5,
)
```

Default limits configured on `FalconRateLimiter` do not currently accept
`cost`. When weighted middleware limits are needed, configure the middleware
limit explicitly with `requests`, `per`, and `cost`.

`cost` callables are synchronous and should be fast. Return a positive integer.
Invalid callable return values raise `ValueError`.

## Conditional exemptions

Use `exempt_when` when a specific limit should be skipped for selected requests.
The predicate receives the Falcon request and should return `True` when the
limit should not run.

```python
class InternalStatusResource:
    @limiter.rate_limit(
        requests=10,
        per=relativedelta(minutes=1),
        exempt_when=lambda req: req.get_header("X-Internal") == "true",
    )
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.text = "ok"
```

Requests skipped by `exempt_when` do not resolve the client key, do not consume
quota, and do not produce a `429` from that limit.

The predicate is synchronous and should be fast. Use request-local information
such as headers, path, method, remote address, or values already attached by
earlier middleware. Do not perform database, cache, HTTP, filesystem, or sleep
operations inside `exempt_when`.

`exempt_when` is also supported by explicit middleware limits:

```python
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=100,
    per=relativedelta(minutes=1),
    exempt_when=lambda req: req.get_header("X-Internal") == "true",
)
```

Default limits configured on `FalconRateLimiter` do not currently accept an
`exempt_when` predicate:

```python
limiter = FalconRateLimiter(
    default_requests=100,
    default_per=relativedelta(minutes=1),
)
middleware = FalconRateLimitMiddleware(limiter)
```

When conditional middleware exemptions are needed, configure the middleware
limit explicitly with `requests`, `per`, and `exempt_when`.

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

### Strategy selection

The limiter uses the fixed-window strategy by default. You can choose a
different `limits` strategy at construction time:

```python
from limiter.constants import MOVING_WINDOW_STRATEGY

limiter = FalconRateLimiter(strategy=MOVING_WINDOW_STRATEGY)
```

Exported strategy constants:

- `FIXED_WINDOW_STRATEGY`
- `MOVING_WINDOW_STRATEGY`
- `SLIDING_WINDOW_COUNTER_STRATEGY`

The configured strategy applies to both the primary storage backend and the
in-memory fallback backend.

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

Versions follow [Semantic Versioning](https://semver.org/), and
`pyproject.toml` is the source of truth for the published package version.

### CI behavior

- Pull requests run CI.
- Pushes to `main` run CI again after merge.
- CI runs linting, type-checking, unit tests, package builds, and the Redis-backed
  e2e suite.
- Merging to `main` does **not** publish a release by itself.

### Release behavior

Publishing happens only when GitHub receives a tag in the `vX.Y.Z` format, such
as `v0.1.1`.

The publish workflow checks that:

1. the tag is a valid semantic version tag
2. the tag matches `project.version` in `pyproject.toml`

If either check fails, the release stops before uploading to PyPI.

### Makefile helpers

```bash
make version        # print the current package version
make release        # bump patch version (default)
make release-minor  # bump minor version
make release-major  # bump major version
make release-tag    # create git tag vX.Y.Z from pyproject.toml
```

`make release` is intentionally an alias for `make release-patch`, so patch
releases are the default path.

### Release steps

1. Run `make release` for a patch release, or `make release-minor` / `make release-major` when needed.
2. Update `CHANGELOG.md` for the new version.
3. Commit the version and changelog changes.
4. Merge that change to `main`.
5. Check out the updated `main` branch locally.
6. Run `make release-tag`.
7. Push the tag with `git push origin vX.Y.Z`.

Once the tag is pushed, GitHub Actions builds the package and publishes it to
PyPI.

### Dependency updates

Dependabot keeps `uv` dependencies and GitHub Actions versions up to date.

## Design notes

- limits are backed by `limits.FixedWindowRateLimiter`
- in-memory storage is used by default
- rejected requests raise `falcon.HTTPTooManyRequests`
- middleware can use explicit limits or the limiter's default limit
- `@limiter.exempt` bypasses both decorator and middleware-based checks
