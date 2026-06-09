# Building Resilient APIs with falcon-rate-limiter

Rate limiting sounds simple until your Redis goes down at 3 AM and every request
starts throwing 500s. Or until one bad deployment doubles your traffic and you
realize your fixed-window strategy lets bursts through at window boundaries.

falcon-rate-limiter was designed with these failure modes in mind. This post
walks through the features that make it production-ready: storage fallback with
recovery probing, strategy selection, weighted costs, shared buckets, and the
developer experience that keeps the whole thing maintainable.

## Storage Resilience: Fallback and Recovery

Most rate limiters rely on a central storage backend — typically Redis. When
that backend goes down, you have two bad options:

1. **Crash.** Raise errors on every request. Your rate limiter becomes a
   denial-of-service tool against your own API.
2. **Silently disable.** Swallow the error, skip rate limiting, and hope nobody
   notices. Your API is now unprotected.

falcon-rate-limiter takes a third path: **automatic in-memory fallback with
recovery probing.**

### How It Works

```
┌──────────────┐     healthy     ┌──────────────┐
│   Request    │ ──────────────> │    Redis      │
│   arrives    │                 │   (primary)   │
└──────────────┘                 └──────────────┘
       │
       │  Redis fails
       ▼
┌──────────────┐                 ┌──────────────┐
│   Fallback   │ ──────────────> │   In-memory   │
│   activated  │                 │   storage     │
└──────────────┘                 └──────────────┘
       │
       │  Background recovery probe (exponential backoff)
       │  1s → 2s → 4s → 8s → ... → 60s (max)
       ▼
┌──────────────┐     recovered   ┌──────────────┐
│   Recovery   │ ──────────────> │    Redis      │
│   detected   │                 │   (primary)   │
└──────────────┘                 └──────────────┘
```

When primary storage (say, Redis) becomes unavailable — whether during
initialization or mid-flight — the `StorageController` immediately switches to
an in-memory `MemoryStorage` fallback. Rate limiting continues, just without
distributed state.

The controller then starts **recovery probing**: on each incoming request, it
checks whether enough time has elapsed since the last probe. If so, it pings
the primary backend. The probe interval doubles on each failure (exponential
backoff), capped at a configurable maximum:

```python
limiter = FalconRateLimiter(
    storage_uri="redis://redis:6379/0",
    recovery_backoff_seconds=1.0,       # first probe after 1 second
    max_recovery_backoff_seconds=60.0,  # cap at 1 minute
)
```

When the primary recovers, the controller switches back transparently and resets
the backoff timer. The entire transition is logged:

```
WARNING  Primary storage is unavailable. Switching to in-memory fallback;
         first recovery probe in 1.00 seconds.
WARNING  Primary storage is still unavailable; next recovery probe in 2.00 s.
WARNING  Primary storage is still unavailable; next recovery probe in 4.00 s.
INFO     Primary rate limiter storage recovered; restoring configured backend.
```

### The Fallback Uses the Same Strategy

An easy mistake: switching storage but not strategy. If your primary uses
`moving-window` and your fallback uses `fixed-window`, rate limiting behavior
changes silently during an outage.

falcon-rate-limiter avoids this. The `StorageController` stores the strategy
*class* and instantiates both the primary and fallback limiter with it:

```python
self._primary_limiter = self._strategy_class(self._primary_storage)
self._fallback_limiter = self._strategy_class(self._fallback_storage)
```

Whether you're on Redis or in-memory, the strategy stays consistent.

### swallow_errors: The Last Safety Net

Even with fallback, edge cases can throw — a corrupt key, a connection pool
exhausted at exactly the wrong moment. `swallow_errors` catches these at the
enforcement boundary and logs instead of crashing:

```python
limiter = FalconRateLimiter(
    storage_uri="redis://redis:6379/0",
    swallow_errors=True,
)
```

When enabled, storage exceptions and `ValueError`s from dynamic cost functions
are caught, logged with full tracebacks, and the request proceeds. This is a
deliberate last resort — not a replacement for monitoring.

The scope is intentional: `swallow_errors` only applies to **request-time**
enforcement errors. Static configuration mistakes (like `cost=0`) still raise
immediately during decorator setup, where they should.

## Strategy Selection

The `limits` library supports three rate-limiting strategies, and
falcon-rate-limiter exposes all of them:

| Strategy | Behavior | Best For |
|---|---|---|
| `fixed-window` | Resets counter at fixed intervals | Simple, predictable, low overhead |
| `moving-window` | Sliding window over exact time range | Smooth rate enforcement, no burst at boundaries |
| `sliding-window-counter` | Hybrid: weighted previous + current window | Balance of accuracy and performance |

```python
limiter = FalconRateLimiter(strategy="moving-window")
```

Or via environment:

```bash
export RATELIMIT_STRATEGY=sliding-window-counter
```

### When to Use Which

**`fixed-window`** (default) is fine for most APIs. It's fast and easy to reason
about. The tradeoff: a client can theoretically send 2× the limit across a window
boundary (e.g., 10 requests at 0:59 and 10 more at 1:00 with a 10/min limit).

**`moving-window`** eliminates boundary bursts entirely. Each request is checked
against a true sliding window of the last N seconds. The cost: it requires storing
individual request timestamps, which uses more memory and slightly more CPU.

**`sliding-window-counter`** splits the difference. It interpolates between the
previous and current fixed windows for an approximation of a moving window,
without storing per-request timestamps. A solid choice for high-throughput APIs
where exact precision isn't critical.

## Advanced Decorator Features

### Weighted Costs

Not all requests are equal. A search endpoint is cheap; a bulk export is
expensive. Weight your limits accordingly:

```python
class ExportResource:
    @limiter.rate_limit(
        requests=100,
        per=relativedelta(minutes=1),
        cost=10,  # each export "costs" 10 of the 100-request budget
    )
    def on_post(self, req, resp):
        ...
```

Costs can also be dynamic — computed per-request from headers, body size, or
any other signal:

```python
class UploadResource:
    @limiter.rate_limit(
        requests=1000,
        per=relativedelta(hours=1),
        cost=lambda req: max(1, int(req.content_length or 0) // 1_000_000),
    )
    def on_put(self, req, resp, file_id):
        # 1 unit per MB uploaded
        ...
```

### Method-Aware Limits

A single Falcon resource often handles multiple HTTP methods. By default, they
share one counter. Enable `per_method` for separate budgets:

```python
class DocumentResource:
    @limiter.rate_limit(
        requests=50,
        per=relativedelta(minutes=1),
        per_method=True,
    )
    def on_get(self, req, resp, doc_id):
        ...  # 50 GETs/min

    @limiter.rate_limit(
        requests=10,
        per=relativedelta(minutes=1),
        per_method=True,
    )
    def on_put(self, req, resp, doc_id):
        ...  # 10 PUTs/min (separate counter)
```

### Shared Limit Buckets

Sometimes multiple endpoints should draw from the same pool. A "write budget"
shared across create, update, and delete:

```python
write_limit = limiter.shared_limit(
    requests=20,
    per=relativedelta(minutes=1),
    scope="write-budget",
)

class CreateResource:
    @write_limit
    def on_post(self, req, resp): ...

class UpdateResource:
    @write_limit
    def on_put(self, req, resp, item_id): ...

class DeleteResource:
    @write_limit
    def on_delete(self, req, resp, item_id): ...
```

All three endpoints share the same 20/min counter per client.

### Conditional Exemptions

Hard-code an admin bypass, a health-check skip, or a feature flag:

```python
class IngestResource:
    @limiter.rate_limit(
        requests=100,
        per=relativedelta(minutes=1),
        exempt_when=lambda req: req.get_header("X-Internal-Service") == "true",
    )
    def on_post(self, req, resp):
        ...
```

The predicate receives the full Falcon `Request` — you can check headers,
query params, auth context, anything.

## Developer Experience

A library is only as good as the experience of working with it day to day.
Here's what falcon-rate-limiter invests in beyond the feature set.

### Type Safety Throughout

The entire codebase is typed and verified with mypy in strict mode. Your IDE
gets full autocomplete and error checking:

```python
# mypy catches this at dev time
limiter.rate_limit(requests="ten", per=relativedelta(minutes=1))
#                           ^^^^^ error: str vs int
```

The library ships a `py.typed` marker, so downstream projects using mypy get
type information automatically.

### Operational Logging

Every meaningful state transition is logged through the dedicated
`falcon-rate-limiter` logger. No need to instrument anything — just configure
your logging level:

```python
import logging
logging.getLogger("falcon-rate-limiter").setLevel(logging.INFO)
```

You'll see rate limit hits, storage transitions, recovery probes, and swallowed
errors — all at appropriate log levels (INFO, WARNING, ERROR).

### CI Pipeline

The project ships with a GitHub Actions CI that runs on every PR:

- **Lint** (ruff) — fast, opinionated Python linting
- **Type check** (mypy) — strict type verification
- **Unit tests** (pytest) — across Python 3.10, 3.12, and 3.14
- **Build verification** — wheel + sdist artifacts are built and checked
- **E2E tests** — Docker Compose spins up Redis + Gunicorn and runs
  integration tests against a real app

Pre-commit hooks catch formatting and lint issues before code reaches CI.

### Makefile-Driven Workflow

```bash
make install    # sync dependencies
make check      # lint + typecheck + test (the one command you need)
make format     # auto-format with ruff
make all        # format + check
make e2e        # run E2E tests with Docker
make release    # bump patch version
make release-tag # create matching git tag
```

### Semantic Versioning and Automated Releases

Pushing a `vX.Y.Z` tag triggers automatic publishing to PyPI. The publish
workflow validates that the tag matches `pyproject.toml`'s version before
uploading — no accidental mismatches.

Dependabot keeps both PyPI dependencies and GitHub Actions versions up to date
automatically.

## Putting It All Together

Here's a realistic production configuration:

```python
import falcon
from dateutil.relativedelta import relativedelta
from falcon_rate_limiter import FalconRateLimiter, FalconRateLimitMiddleware

limiter = FalconRateLimiter(
    storage_uri="redis://redis:6379/0",
    strategy="moving-window",
    swallow_errors=True,
    recovery_backoff_seconds=2.0,
    max_recovery_backoff_seconds=30.0,
)

# Baseline: 200 req/min for all undecorated routes
middleware = FalconRateLimitMiddleware(
    limiter,
    requests=200,
    per=relativedelta(minutes=1),
)

app = falcon.App(middleware=[middleware])

# Override for specific endpoints
class SearchResource:
    @limiter.rate_limit(requests=20, per=relativedelta(minutes=1))
    def on_get(self, req, resp):
        ...

# Shared write budget across mutation endpoints
write_limit = limiter.shared_limit(
    requests=50, per=relativedelta(minutes=1), scope="writes"
)

class CreateResource:
    @write_limit
    def on_post(self, req, resp): ...

# Health check is exempt
@limiter.exempt
class HealthResource:
    def on_get(self, req, resp):
        resp.text = "ok"

app.add_route("/search", SearchResource())
app.add_route("/items", CreateResource())
app.add_route("/health", HealthResource())
```

This gives you:

- Moving-window rate limiting backed by Redis
- Automatic fallback to in-memory if Redis goes down
- Recovery probing every 2s → 4s → 8s → ... → 30s
- A 200/min baseline for routes you forgot to decorate
- A tighter 20/min limit on search
- A shared 50/min write budget across creation endpoints
- Health checks that are never rate-limited
- Standard response headers on every request
- Full operational logging

All configurable via environment variables for zero-code deployment changes.
