# falcon-rate-limiter vs slowapi: Rate Limiting Across Python Frameworks

[slowapi](https://github.com/laurents/slowapi) is the established rate limiter for
Starlette and FastAPI. [falcon-rate-limiter](https://github.com/w7089/falcon-rate-limiter)
brings the same core idea to Falcon. Both wrap the
[`limits`](https://limits.readthedocs.io/) library. Both offer decorators, middleware,
storage backends, and response headers.

But they're not ports of each other. Each library is shaped by its framework's
philosophy. This post breaks down what they share, where they diverge, and which
design decisions matter for your project.

## The Shared Foundation

Both libraries build on `limits`, so the core mechanics are identical:

- **Storage backends**: Redis, Memcached, in-memory — all via `limits`' URI-based
  configuration (`redis://`, `memory://`, etc.)
- **Strategy support**: Fixed-window and moving-window strategies from `limits.strategies`
- **Rate limit strings**: The underlying counter logic, window calculation, and
  storage protocol are the same `limits` internals
- **Key-based tracking**: Both identify clients via a configurable key function
  and scope limits to endpoint + client combinations

This shared foundation means rate-limiting *behavior* is consistent. A
"10 requests per minute" limit with a fixed-window strategy enforces the same
way in both libraries. The differences are in how you configure and integrate.

## API Design: String Parsing vs Explicit Parameters

**slowapi** uses limit strings parsed at runtime:

```python
# slowapi
@limiter.limit("10/minute")
async def search(request: Request):
    ...
```

**falcon-rate-limiter** uses typed parameters:

```python
# falcon-rate-limiter
@limiter.rate_limit(requests=10, per=relativedelta(minutes=1))
def on_get(self, req, resp):
    ...
```

### Why It Matters

slowapi's string syntax is concise and familiar if you've used Flask-Limiter
(where the pattern originated). But it's opaque to type checkers — `"10/minute"`
is just a `str`. Typos like `"10/mintue"` are caught at runtime, not at
import time.

falcon-rate-limiter's approach is more verbose but statically checkable. `requests`
is an `int`, `per` is a `relativedelta`. Your IDE catches type mismatches before
you run the code. The tradeoff is that `relativedelta(minutes=1)` is wordier than
`"1/minute"`.

slowapi also supports **dynamic limit strings** via callables:

```python
# slowapi — limit can change per-request
@limiter.limit(lambda: "100/hour" if is_premium() else "10/hour")
async def endpoint(request: Request):
    ...
```

falcon-rate-limiter doesn't have this pattern. Limits are fixed at decoration
time. For conditional logic, you'd use `exempt_when` or different decorators on
different resource classes.

## Framework Integration

### Falcon: Resource Classes and Responder Methods

Falcon's architecture is resource-oriented. An endpoint is a class with
`on_get`, `on_post`, etc. falcon-rate-limiter is designed around this:

```python
# Decorate the whole class — all on_* methods get the same limit
@limiter.rate_limit(requests=20, per=relativedelta(minutes=1))
class ArticleResource:
    def on_get(self, req, resp): ...
    def on_post(self, req, resp): ...

# Or just one method
class UserResource:
    @limiter.rate_limit(requests=5, per=relativedelta(minutes=1))
    def on_post(self, req, resp): ...

    def on_get(self, req, resp): ...  # no limit
```

### Starlette/FastAPI: Function-Based Routes

slowapi targets function-based route handlers:

```python
@app.get("/search")
@limiter.limit("10/minute")
async def search(request: Request):
    ...
```

FastAPI's dependency injection means the `Request` object must be explicitly
declared in the function signature for slowapi to find it — a common source of
confusion for new users.

### Class-Level Decoration

falcon-rate-limiter supports class-level decoration natively — one decorator wraps
every responder method in the class. slowapi doesn't have a direct equivalent.
You decorate each route function individually, or use `default_limits` for a
global baseline.

## Middleware Architecture

Both libraries offer middleware, but the integration patterns differ.

**slowapi** provides two middleware classes:
- `SlowAPIMiddleware` — wraps Starlette's `BaseHTTPMiddleware`
- `SlowAPIASGIMiddleware` — pure ASGI middleware (more efficient)

The limiter is attached to the app via `app.state.limiter`, and the middleware
reads it from there:

```python
# slowapi
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
```

**falcon-rate-limiter** has a single middleware class that handles both WSGI and
ASGI via Falcon's `process_resource` / `process_resource_async` hooks:

```python
# falcon-rate-limiter
middleware = FalconRateLimitMiddleware(limiter, requests=100, per=relativedelta(minutes=1))
app = falcon.App(middleware=[middleware])
```

Key difference: falcon-rate-limiter's middleware **intelligently skips** routes
that already have `@rate_limit` decorators. It checks for the internal
`__falcon_rate_limited__` marker on both the responder and resource class. slowapi
achieves similar behavior by tracking decorated routes in an internal set.

## Storage Resilience: A Clear Differentiator

This is where the libraries diverge most sharply.

### slowapi's Fallback

slowapi supports in-memory fallback when the primary backend fails:

```python
# slowapi
limiter = Limiter(
    key_func=get_ipaddr,
    storage_uri="redis://redis:6379",
    in_memory_fallback_enabled=True,
    in_memory_fallback=["100/hour"],  # fallback limits (can differ!)
)
```

Recovery probing uses a power-of-2 backoff: 1s, 2s, 4s, 8s, 16s, 32s — and then
**stops checking** after a fixed number of attempts. If your Redis comes back
after attempt 5, slowapi won't notice until the process restarts.

The fallback limits can also be *different* from the primary limits — by design,
since you might want more restrictive limits when running without distributed state.

### falcon-rate-limiter's Fallback

falcon-rate-limiter takes a different approach:

```python
# falcon-rate-limiter
limiter = FalconRateLimiter(
    storage_uri="redis://redis:6379/0",
    recovery_backoff_seconds=1.0,
    max_recovery_backoff_seconds=60.0,
)
```

1. **Recovery never stops.** Backoff is capped at a maximum (default 60s), not
   a maximum *count*. The controller keeps probing indefinitely — if Redis
   recovers after an hour, the limiter switches back automatically.

2. **Same limits, same strategy.** The fallback uses the same rate-limiting
   strategy class as the primary. There's no separate `in_memory_fallback` limit
   config. The idea: during an outage, behavior should be as consistent as
   possible, even if state is lost.

3. **Explicit primary/fallback objects.** Internally, the `StorageController`
   maintains separate `_primary_limiter` and `_fallback_limiter` instances with a
   clear `_using_fallback` boolean. No mutable "active" object with shifting
   meaning.

4. **Configurable backoff.** Both the initial delay and the cap are constructor
   parameters (and environment variables). slowapi's backoff schedule is
   hardcoded.

### Side-by-Side

| Aspect | slowapi | falcon-rate-limiter |
|---|---|---|
| Fallback limits | Configurable (can differ from primary) | Same as primary |
| Strategy consistency | Not guaranteed during fallback | Same strategy class for both |
| Recovery probing | Stops after fixed attempts | Continues indefinitely with capped backoff |
| Backoff config | Hardcoded power-of-2 | Configurable initial + max |
| State model | Mutable `_storage_dead` flag | Explicit primary/fallback objects |

## Exemptions

Both libraries support exemptions, but with different ergonomics.

**slowapi:**

```python
@limiter.exempt
@app.get("/health")
async def health(request: Request):
    return PlainTextResponse("ok")
```

**falcon-rate-limiter** supports three levels:

```python
# Method-level
class MyResource:
    @limiter.exempt
    def on_get(self, req, resp): ...

# Class-level
@limiter.exempt
class HealthResource:
    def on_get(self, req, resp): ...

# Instance-level (at runtime)
resource = MyResource()
limiter.exempt(resource)
```

The instance-level exemption is unique to falcon-rate-limiter and useful when the
same resource class is mounted at multiple routes with different rate-limiting
needs.

## Feature Comparison Table

| Feature | slowapi | falcon-rate-limiter |
|---|---|---|
| **Framework** | Starlette / FastAPI | Falcon (WSGI + ASGI) |
| **Limit syntax** | String (`"10/minute"`) | Typed (`requests=10, per=relativedelta(...)`) |
| **Dynamic limits** | ✅ Callable limit strings | ❌ Fixed at decoration time |
| **Class-level decoration** | ❌ | ✅ Wraps all `on_*` methods |
| **Middleware** | Two variants (HTTP + ASGI) | Single class, dual hooks |
| **Skip decorated routes** | ✅ (internal route set) | ✅ (attribute marker) |
| **Key function default** | None (required) | `get_remote_address` (built-in) |
| **Storage fallback** | ✅ (configurable limits) | ✅ (same limits, same strategy) |
| **Recovery probing** | Stops after N attempts | Indefinite with capped backoff |
| **Strategy selection** | ✅ (`fixed-window`, `moving-window`) | ✅ (+ `sliding-window-counter`) |
| **per_method** | ✅ | ✅ |
| **Weighted cost** | ✅ (static + callable) | ✅ (static + callable) |
| **Shared limits** | ✅ (`shared_limit`) | ✅ (`shared_limit`) |
| **exempt_when** | ✅ | ✅ |
| **Response headers** | ✅ (customizable names) | ✅ (standard names) |
| **Header name config** | ✅ Per-header env vars | ❌ Standard names only |
| **Env var config** | ✅ (.env file via Starlette Config) | ✅ (`os.environ` direct) |
| **swallow_errors** | ✅ | ✅ (scoped to request-time only) |
| **enabled toggle** | ✅ | ✅ |
| **Type safety** | Partial (type hints, mypy in CI) | Full (mypy strict, `py.typed`) |
| **Custom error handler** | ✅ (Starlette exception handler) | Via Falcon error handlers |
| **Retry-After header** | ✅ (http-date or seconds) | ✅ (seconds) |

## Design Philosophy

The libraries reflect their frameworks' values.

**slowapi** is *flexible*. Dynamic limit strings, configurable header names,
separate fallback limits, `.env` file parsing — it gives you knobs for
everything. This mirrors FastAPI's "batteries-included, everything-configurable"
ethos.

**falcon-rate-limiter** is *explicit*. Typed parameters over magic strings.
Same limits during fallback (no hidden behavior change). Constructor arguments
over app-state mutation. Instance-level exemptions over global route sets.
This mirrors Falcon's "explicit is better than implicit" philosophy.

Neither approach is strictly better — they serve different developer preferences
and framework cultures.

## When to Use Which

**Choose slowapi if:**
- You're on FastAPI or Starlette
- You want dynamic limits that change per-request
- You need custom header names for legacy client compatibility
- You prefer concise string-based limit definitions

**Choose falcon-rate-limiter if:**
- You're on Falcon (WSGI or ASGI)
- You value type safety and IDE support
- You want resilient storage fallback that recovers automatically
- You need class-level decoration and instance-level exemptions
- You prefer environment-variable-driven deployment configuration

## Both Are Good

The Python rate-limiting ecosystem is better with both libraries. They share the
same `limits` foundation, so switching between them requires minimal conceptual
overhead. If you know one, you'll understand the other in minutes.

The real differentiator isn't features — it's framework fit. Use the library built
for your framework, and you'll get an API that feels native rather than adapted.
