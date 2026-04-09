# Falcon Rate Limiter Copilot Instructions

This repository implements a rate limiter for the Falcon web framework, wrapping the `limits` library.

# Implementation flow:

- Work in phases. Each phase should produce a working, testable increment, and tests should ship with the feature instead of being deferred.
- Before implementing, review the current plan and compare the design with Falcon, `limits`, and the local `../slowapi` implementation. Use slowapi as the default reference for integration patterns, then adapt them cleanly to Falcon.
- Prefer explicit, call-site-readable names and APIs. If a method name or flow is hard to understand where it is used, rename or redesign it instead of explaining away the confusion in comments.
- Keep modules and functions small and focused. Favor simple control flow with low mental overhead over clever abstractions or generic indirection.
- Prefer explicit state over implicit state. If code manages modes such as primary/fallback, decorated/undecorated, or sync/async, model those states directly instead of hiding them behind mutable “current” objects with shifting meaning.
- Separate queries from commands when possible: accessors should describe current state, while methods with side effects should sound like actions. Do not hide meaningful state changes behind innocent-sounding getters.
- Prefer composition over inheritance for integration logic. Wrap `limits` and Falcon behaviors in small coordinating objects instead of subclassing framework/library internals unless there is a clear benefit.
- Keep retry, fallback, and recovery logic close to the boundary where failures happen. Do not spread resilience state changes across unrelated helpers or decorators.
- Minimize `Any` in implementation code. Use concrete types when the abstraction is known, and only fall back to `Any` at framework boundaries that genuinely require it.
- Make boolean flags and config names describe behavior, not mechanism. Prefer names like `limit_undecorated_routes` over vague names like `auto_check`.
- Avoid calling private members from dependencies or framework internals.
- Think through failure modes early: storage outages, invalid configuration, async behavior, middleware interactions, and fallback/recovery paths should be implemented and tested deliberately.
- Cover new behavior across the surfaces it affects: unit tests, async/ASGI tests, and e2e tests when the feature touches integration points such as middleware, storage backends, or distributed behavior.
- Document every shipped feature in `README.md` with practical examples and different usage scenarios, and add function docstrings that explain purpose, parameters, return values, exceptions, and any non-obvious reasoning.
- Use logging for meaningful operational events, especially storage failures, fallback activation, and recovery. Choose log levels intentionally.
- Prefer curated project-specific guidance over imported generic prompts. If borrowing an idea from external instruction sets, adapt it to Falcon, `limits`, and this repository's architecture before adding it here.
- After feedback about naming, readability, or structure, update this implementation flow with the lesson so the same mistake is less likely to happen again.
- Recent lesson: do not expose internal scheduling details in public method names (for example, `...if_due`). Prefer names that describe the caller's intent, and if the call flow still feels awkward, redesign the API so the call site reads naturally.
- Recent lesson: avoid mutating a generic “active” object when separate named state is clearer. For fallback/recovery flows, prefer explicit primary/fallback objects plus a clear selector over hidden state changes.
- Recent lesson: extract repeated user-visible strings and operational log messages into a shared constants module, and use those constants in tests instead of duplicating raw strings.
- Recent lesson: keep subsystem-focused tests in dedicated files, and use parametrized tests for repeated validation cases when that improves readability without fighting the type system.
- End implementation by reviewing the code, validating with the repository checks, and summarizing the educational takeaway from the change.

## Build, Test, and Lint Commands

- **Run all tests:** `pytest`
- **Run a single test file:** `pytest tests/test_limiter.py`
- **Run a specific test case:** `pytest tests/test_limiter.py::test_rate_limit_allows_requests`
- **Install dependencies:** `uv sync` (project uses `uv` for dependency management)

## High-Level Architecture

## Code Review
- After implementing features or fixes, always perform a code review and make any necessary corrections based on the review before considering the work complete.
- Run `make check` and fix testing, linting or static type checking errors.


### Core Components
- **`FalconRateLimiter` (`limiter/core.py`):** The main entry point. It initializes the storage (default: in-memory) and strategy (configurable via ``strategy`` param or ``RATELIMIT_STRATEGY`` env var; default: ``fixed-window``).
- **Decorators:** The `rate_limit` method provides a decorator that can be applied to:
  - **Individual Responder Methods:** (e.g., `on_get`, `on_post`).
  - **Resource Classes:** Automatically decorates all methods starting with `on_` within the class.
- **Storage:** Uses `limits.storage.MemoryStorage` by default but supports any storage backend from the `limits` library (e.g., Redis).
- **Async Support:** Detects `async` responders via `inspect.iscoroutinefunction` and wraps them to run the synchronous `limits` check in a thread pool (`asyncio.to_thread`) to avoid blocking the event loop.

### Request Flow
1.  **Decorator Execution:**
    -   Extracts `req` and `resp` from the responder arguments.
    -   Resolves the rate limit key (see Conventions).
    -   Checks the limit against the storage strategy.
2.  **Limit Exceeded:**
    -   Raises `falcon.HTTPTooManyRequests`.
    -   Lets Falcon handle serialization and response generation.
    -   Includes the configured rejection message and retry metadata.
3.  **Allowed:**
    -   Proceeds to execute the original responder method.

## Comparisons with Slowapi

The implementation logic aligns with `slowapi` (Starlette extension) in several ways:
-   **Key Functions:** Both use `key_func` to determine the client identifier. `slowapi` checks if `key_func` accepts a `request` argument and passes it if so; otherwise, it calls it without arguments. `falcon-rate-limiter` currently enforces `key_func` to take `req` as an argument.
-   **Global Fallback:** `slowapi` uses `"global"` as the fallback string when a limit is applied globally (application-wide) and no specific key is generated. `falcon-rate-limiter` uses `"global"` as a fallback when `key_func` returns a falsy value (e.g. `None` or empty string).
-   **Default Key Function:** `slowapi` provides `get_remote_address` (client IP) as a common default. `falcon-rate-limiter` defaults to `req.remote_addr` or "global".
-   **Limit Groups:** `slowapi` groups limits. `falcon-rate-limiter` applies limits per decorator but allows stacking.

**Guideline for Future Features:** When implementing new features, refer to `slowapi` as a reference implementation where applicable, adapting its patterns to Falcon's architecture. For `key_func`, the use of "global" as a fallback is consistent with `slowapi`'s approach for application-wide limits, but we use it for unidentified clients.

## Key Conventions

### Rate Limit Keys & Identification
-   **Key Format:** Limits are tracked using a composite key: `{QualifiedName}:{ClientID}`.
    -   `QualifiedName`: The fully qualified name of the decorated method (e.g., `Resource.on_get`).
    -   `ClientID`: Derived from the `key_func`.
-   **Key Function Resolution:**
    1.  **Per-Decorator Override:** `key_func` passed to `@rate_limit(...)`.
    2.  **Global Default:** `key_func` passed to `FalconRateLimiter(...)`.
    3.  **Fallback:** If no function is provided or the function returns a falsy value, defaults to `req.remote_addr` or "global".
-   **Signature:** Key functions must accept a single argument: `def key_func(req: falcon.Request) -> str`.

### Time Periods
-   Use `dateutil.relativedelta.relativedelta` for defining rate limit periods (e.g., `requests=5, per=relativedelta(minutes=1)`).
-   Supported granularities: seconds, minutes, hours, days, months, years.

### Responder Signature
-   Wrapped responders **must** accept `self, req, resp` as the first three arguments. The decorator explicitly checks `len(args) >= 3` to extract `req` (index 1) and `resp` (index 2).
