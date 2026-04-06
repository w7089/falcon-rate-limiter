# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-06

### Added
- Decorator-based rate limiting for Falcon responders and resource classes
- Async and middleware-based limiting support
- Per-client key functions and response headers
- URI-configured storage backends with in-memory fallback and recovery probing
- Exemption support for responders, classes, and resource instances
- End-to-end tests for middleware and Redis-backed storage
