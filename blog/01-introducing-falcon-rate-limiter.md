# Introducing falcon-rate-limiter: Practical Rate Limiting for Falcon

If you're building APIs with [Falcon](https://falconframework.org/), you've probably noticed
the ecosystem gap: there's no go-to rate-limiting library the way
[slowapi](https://github.com/laurents/slowapi) serves FastAPI and Starlette.

**falcon-rate-limiter** fills that gap. It wraps the battle-tested
[`limits`](https://limits.readthedocs.io/) library and gives you decorator-based,
middleware-driven rate limiting that works with both WSGI and ASGI Falcon apps —
right out of the box.

```bash
pip install falcon-rate-limiter
```

## The 30-Second Tour

```python
import falcon
from dateutil.relativedelta import relativedelta
from falcon_rate_limiter import FalconRateLimiter

limiter = FalconRateLimiter()

class SearchResource:
    @limiter.rate_limit(requests=10, per=relativedelta(minutes=1))
    def on_get(self, req, resp):
        resp.media = {"results": [...]}

app = falcon.App()
app.add_route("/search", SearchResource())
```

That's it. Clients exceeding 10 requests per minute get a `429 Too Many Requests`
with a clear error body, and successful rate-limited responses include standard
headers so clients know exactly where they stand:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1712700000
```

## Why Another Library?

The Python rate-limiting space has great tools for other frameworks — slowapi for
Starlette/FastAPI, Flask-Limiter for Flask — but Falcon users have been left to
roll their own. That means duplicated boilerplate, inconsistent error handling, and
reinvented fallback logic in every project.

falcon-rate-limiter brings the patterns proven in those libraries and adapts them
to Falcon's resource-oriented architecture:

- **Decorators feel native.** Apply `@limiter.rate_limit()` to a responder method
  or an entire resource class — the library discovers `on_get`, `on_post`, etc.
  automatically.
- **Async is a first-class citizen.** ASGI responders are detected at decoration
  time. Blocking `limits` storage calls are transparently offloaded to a thread
  pool via `asyncio.to_thread`, so your event loop never stalls.
- **Middleware fills the gaps.** For routes you didn't decorate,
  `FalconRateLimitMiddleware` applies a configurable default limit — and
  intelligently skips routes that already have explicit decorators.

## Feature Highlights

### Decorate Methods, Classes, or Both

```python
# Single method
class UserResource:
    @limiter.rate_limit(requests=30, per=relativedelta(minutes=1))
    def on_get(self, req, resp, user_id):
        ...

# Entire class — all on_* methods get the same limit
@limiter.rate_limit(requests=20, per=relativedelta(minutes=1))
class ArticleResource:
    def on_get(self, req, resp): ...
    def on_post(self, req, resp): ...
```

### Stack Multiple Limits

Real APIs often need layered policies: a burst limit *and* a sustained limit.
Stack decorators — each one is enforced independently.

```python
class ApiResource:
    @limiter.rate_limit(requests=5, per=relativedelta(seconds=1))    # burst
    @limiter.rate_limit(requests=100, per=relativedelta(minutes=1))  # sustained
    def on_get(self, req, resp):
        resp.media = {"data": "..."}
```

### Automatic Middleware for Undecorated Routes

Decorating every route is tedious. Middleware gives you a baseline:

```python
from falcon_rate_limiter import FalconRateLimiter, FalconRateLimitMiddleware

limiter = FalconRateLimiter()
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=100,
    per=relativedelta(minutes=1),
)

app = falcon.App(middleware=[middleware])
# Every route gets 100/min unless it has its own @rate_limit
```

Routes with explicit `@rate_limit` decorators are detected and skipped by the
middleware to avoid double-counting.

### Exemptions — Surgical and Conditional

Some routes shouldn't be limited. Mark them:

```python
@limiter.exempt
class HealthResource:
    def on_get(self, req, resp):
        resp.text = "ok"
```

Or conditionally, per request:

```python
class AdminResource:
    @limiter.rate_limit(
        requests=10,
        per=relativedelta(minutes=1),
        exempt_when=lambda req: req.get_header("X-Admin-Key") == SECRET,
    )
    def on_post(self, req, resp):
        ...
```

### Async Just Works

```python
import falcon.asgi

limiter = FalconRateLimiter()

class AsyncResource:
    @limiter.rate_limit(requests=5, per=relativedelta(seconds=10))
    async def on_get(self, req, resp):
        resp.media = {"status": "ok"}

app = falcon.asgi.App()
app.add_route("/async", AsyncResource())
```

The library detects the coroutine and wraps the blocking storage call in
`asyncio.to_thread` — no configuration needed.

### Explicit Runtime Configuration

Deployment choices are explicit at application startup. Pass constructor
arguments for storage, strategy, headers, default middleware limits, and recovery
backoff:

```python
import os

from falcon_rate_limiter import FalconRateLimiter
from falcon_rate_limiter.constants import MOVING_WINDOW_STRATEGY

storage_uri = os.environ.get("APP_RATE_LIMIT_STORAGE_URI", "memory://")

limiter = FalconRateLimiter(
    storage_uri=storage_uri,
    strategy=MOVING_WINDOW_STRATEGY,
    headers_enabled=True,
    recovery_backoff_seconds=1.0,
    max_recovery_backoff_seconds=60.0,
)
```

If you use a `redis://` storage URI, install the Redis extra:

```bash
pip install "falcon-rate-limiter[redis]"
```

Built-in `RATELIMIT_*` environment-variable loading is planned, but it is not
part of the current public API.

## What's Next

This was the quick tour. In the next posts we'll dive into:

- **[Storage resilience](./02-building-resilient-apis.md)** — how
  falcon-rate-limiter handles Redis outages with automatic fallback and recovery
  probing
- **[Comparison with slowapi](./03-falcon-rate-limiter-vs-slowapi.md)** — a
  side-by-side look at design decisions, feature parity, and where each library
  shines

The project is open-source on GitHub. The PyPI install path is:

```bash
pip install falcon-rate-limiter
pip install "falcon-rate-limiter[redis]"  # Redis-backed storage
```

The base install is enough for in-memory rate limiting. Install the Redis extra
only when you need persistent or distributed counters across workers or hosts.

Contributions and feedback welcome on
[GitHub](https://github.com/w7089/falcon-rate-limiter).
