# Building Resilient APIs with falcon-rate-limiter

Rate limiting sounds simple until your Redis goes down at 3 AM and every request
starts throwing 500s. Or until one bad deployment doubles your traffic and you
realize your fixed-window strategy lets bursts through at window boundaries.

falcon-rate-limiter was designed with these failure modes in mind. This post
walks through the features that make it practical for real APIs: storage
fallback with recovery probing, strategy selection, weighted costs, shared
buckets, and the developer experience that keeps the whole thing maintainable.

## Storage Resilience: Fallback and Recovery

Most rate limiters rely on a central storage backend — typically Redis. When
that backend goes down, you have two bad options:

1. **Crash.** Raise errors on every request. Your rate limiter becomes a
   denial-of-service tool against your own API.
2. **Silently disable.** Swallow the error, skip rate limiting, and hope nobody
   notices. Your API is now unprotected.

falcon-rate-limiter takes a third path: **automatic in-memory fallback with
recovery probing.**

Redis-backed storage requires the optional Redis extra:

```bash
pip install "falcon-rate-limiter[redis]"
```

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

### What Fallback Does Not Hide

The fallback path is deliberately narrow. Storage backend failures can activate
the in-memory fallback, and the request is retried against that fallback backend.
Unexpected errors still raise instead of being silently ignored.

That means invalid configuration and invalid dynamic cost results fail loudly.
A broader `swallow_errors` option is planned, but it is not part of the current
public API.

## Strategy Selection

The `limits` library supports three rate-limiting strategies, and
falcon-rate-limiter exposes all of them:

| Strategy | Behavior | Best For |
|---|---|---|
| `fixed-window` | Resets counter at fixed intervals | Simple, predictable, low overhead |
| `moving-window` | Sliding window over exact time range | Smooth rate enforcement, no burst at boundaries |
| `sliding-window-counter` | Hybrid: weighted previous + current window | Balance of accuracy and performance |

```python
from falcon_rate_limiter.constants import MOVING_WINDOW_STRATEGY

limiter = FalconRateLimiter(strategy=MOVING_WINDOW_STRATEGY)
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

The package code is typed and verified with mypy in CI. Your IDE gets useful
autocomplete and error checking:

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

You'll see storage failures, fallback activation, failed recovery probes, and
successful primary-storage recovery at appropriate log levels.

### CI Pipeline

The project ships with GitHub Actions workflows for pull requests, pushes to
`main`, and release tags:

- **Lint** (ruff) — fast, opinionated Python linting
- **Type check** (mypy) — package type verification
- **Unit tests** (pytest) — across Python 3.10 through 3.14
- **Build verification** — wheel + sdist artifacts are built and checked
- **E2E tests** — Docker Compose spins up Redis + Gunicorn on `main` pushes and
  release tags, then runs integration tests against a real app

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

Once PyPI Trusted Publishing is configured, pushing a `vX.Y.Z` tag triggers
publishing to PyPI. The publish workflow validates that the tag matches
`pyproject.toml`'s version before uploading — no accidental mismatches.

Dependabot keeps both Python dependencies and GitHub Actions versions up to date
automatically.

## Putting It All Together

Here's a realistic Redis-backed configuration:

```python
import falcon
from dateutil.relativedelta import relativedelta
from falcon_rate_limiter import FalconRateLimiter, FalconRateLimitMiddleware
from falcon_rate_limiter.constants import MOVING_WINDOW_STRATEGY

limiter = FalconRateLimiter(
    storage_uri="redis://redis:6379/0",
    strategy=MOVING_WINDOW_STRATEGY,
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
- Standard response headers on rate-limited requests
- Storage failure, fallback, and recovery logging

Configuration is explicit in application startup code; if you want
environment-driven deployment, read environment variables in your app and pass
the resolved values to `FalconRateLimiter`.
