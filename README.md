# Falcon Rate Limiter

### Design decisions and trade-offs
- Decorators wrap Falcon responders (sync or async) and class-level resources.
- Limits are backed by `limits.FixedWindowRateLimiter` with an in-memory store by default.

### Per-client key functions (feature 1.1)
Rate limits can be tracked per client by providing a key function when creating the limiter or per decorator.

```python
from dateutil.relativedelta import relativedelta
from limiter.core import FalconRateLimiter

def client_key(req):
    return req.get_header("X-Client-Id") or req.remote_addr or "global"

limiter = FalconRateLimiter(key_func=client_key)

@limiter.rate_limit(requests=5, per=relativedelta(minutes=1))
def on_get(self, req, resp):
    ...

# Override per responder or class
@limiter.rate_limit(requests=1, per=relativedelta(seconds=1), key_func=client_key)
class Resource:
    def on_get(self, req, resp):
        ...
```

If the key function returns a falsy value, the limiter falls back to `"global"`.
