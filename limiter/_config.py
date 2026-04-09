"""Environment-backed defaults for limiter configuration.

Each ``get_optional_*_env`` helper reads a single variable, returning
``None`` when the variable is unset so constructor arguments can take
precedence over environment defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from limiter.constants import (
    RATELIMIT_ENABLED_ENV,
    RATELIMIT_HEADERS_ENABLED_ENV,
    RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV,
    RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV,
    RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV,
    RATELIMIT_STORAGE_URL_ENV,
    RATELIMIT_STRATEGY_ENV,
    RATELIMIT_SWALLOW_ERRORS_ENV,
)

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSY_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class LimiterEnvironmentConfig:
    """Parsed environment-backed defaults for the rate limiter.

    Attributes:
        enabled: Optional default for globally enabling rate limiting.
        headers_enabled: Optional default for response header injection.
        storage_uri: Optional default storage backend URI.
        strategy: Optional default rate-limiting strategy name.
        limit_undecorated_routes: Optional default for middleware limiting of
            undecorated routes.
        swallow_errors: Optional default for request-time limiter error handling.
        recovery_backoff_seconds: Optional default recovery probe delay.
        max_recovery_backoff_seconds: Optional default maximum recovery probe delay.
    """

    enabled: bool | None = None
    headers_enabled: bool | None = None
    storage_uri: str | None = None
    strategy: str | None = None
    limit_undecorated_routes: bool | None = None
    swallow_errors: bool | None = None
    recovery_backoff_seconds: float | None = None
    max_recovery_backoff_seconds: float | None = None


def load_environment_config(
    environ: Mapping[str, str] | None = None,
) -> LimiterEnvironmentConfig:
    """Load limiter defaults from environment variables.

    Args:
        environ: Mapping to read values from. Defaults to ``os.environ``.

    Returns:
        Parsed limiter environment configuration. Missing variables remain ``None``
        so constructor arguments can continue to take precedence.

    Raises:
        ValueError: When a configured boolean or float environment variable has an
            unsupported value.
    """

    resolved_environ = os.environ if environ is None else environ
    return LimiterEnvironmentConfig(
        enabled=get_optional_bool_env(RATELIMIT_ENABLED_ENV, resolved_environ),
        headers_enabled=get_optional_bool_env(
            RATELIMIT_HEADERS_ENABLED_ENV, resolved_environ
        ),
        storage_uri=get_optional_string_env(
            RATELIMIT_STORAGE_URL_ENV, resolved_environ
        ),
        strategy=get_optional_string_env(RATELIMIT_STRATEGY_ENV, resolved_environ),
        limit_undecorated_routes=get_optional_bool_env(
            RATELIMIT_LIMIT_UNDECORATED_ROUTES_ENV, resolved_environ
        ),
        swallow_errors=get_optional_bool_env(
            RATELIMIT_SWALLOW_ERRORS_ENV, resolved_environ
        ),
        recovery_backoff_seconds=get_optional_float_env(
            RATELIMIT_RECOVERY_BACKOFF_SECONDS_ENV, resolved_environ
        ),
        max_recovery_backoff_seconds=get_optional_float_env(
            RATELIMIT_MAX_RECOVERY_BACKOFF_SECONDS_ENV, resolved_environ
        ),
    )


def get_optional_bool_env(
    env_name: str,
    environ: Mapping[str, str] | None = None,
) -> bool | None:
    """Read an optional boolean environment variable.

    Args:
        env_name: Variable name to read.
        environ: Environment mapping to inspect. Defaults to ``os.environ``.

    Returns:
        ``None`` when the variable is unset, otherwise the parsed boolean value.

    Raises:
        ValueError: When the variable is set to an unsupported boolean string.
    """

    resolved_environ = os.environ if environ is None else environ
    raw_value = resolved_environ.get(env_name)
    if raw_value is None:
        return None

    normalized = raw_value.strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    raise ValueError(
        f"{env_name} must be one of {_TRUTHY_VALUES | _FALSY_VALUES}, got {raw_value!r}"
    )


def get_optional_float_env(
    env_name: str,
    environ: Mapping[str, str] | None = None,
) -> float | None:
    """Read an optional floating-point environment variable.

    Args:
        env_name: Variable name to read.
        environ: Environment mapping to inspect. Defaults to ``os.environ``.

    Returns:
        ``None`` when the variable is unset, otherwise the parsed float value.

    Raises:
        ValueError: When the variable is set but cannot be parsed as a float.
    """

    resolved_environ = os.environ if environ is None else environ
    raw_value = resolved_environ.get(env_name)
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a float, got {raw_value!r}") from exc


def get_optional_string_env(
    env_name: str,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Read an optional string environment variable.

    Args:
        env_name: Variable name to read.
        environ: Environment mapping to inspect. Defaults to ``os.environ``.

    Returns:
        The raw string value when present, otherwise ``None``.
    """

    resolved_environ = os.environ if environ is None else environ
    return resolved_environ.get(env_name)
