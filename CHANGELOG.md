# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Method-aware rate limits via `per_method` flag for separate counters per HTTP method
- Conditional exemptions via `exempt_when` callable predicate
- Weighted request costs via `cost` parameter (static int or request-based callable)
- Shared limit buckets via `shared_key` for cross-endpoint limits
- Configuration and logging: `enabled`, `swallow_errors`, `headers_enabled`,
  `limit_undecorated_routes` toggles with environment variable fallbacks
- Strategy selection: `strategy` parameter supporting `"fixed-window"`,
  `"moving-window"`, and `"sliding-window-counter"` (via constructor or
  `RATELIMIT_STRATEGY` env var)

### Changed
- `get_remote_address` is now a public export (previously `_get_remote_address`)
- `redis` moved from hard dependency to optional extra (`pip install falcon-rate-limiter[redis]`)
- Middleware guard logic extracted to `_should_enforce()` to reduce sync/async duplication
- Config resolution uses `_first_of()` helper to replace nested ternary chains

## [0.1.0] - 2026-04-06

### Added
- Decorator-based rate limiting for Falcon responders and resource classes
- Async and middleware-based limiting support
- Per-client key functions and response headers
- URI-configured storage backends with in-memory fallback and recovery probing
- Exemption support for responders, classes, and resource instances
- End-to-end tests for middleware and Redis-backed storage
