# Publication Readiness Report

Last inspected: 2026-06-09

## Verdict

The project is publishable as an alpha package. The import package now uses the unique public name `falcon_rate_limiter`, matching the normalized PyPI distribution name `falcon-rate-limiter`.

Local validation passed:

| Check | Result |
|---|---|
| `make check` | Passed: ruff, mypy, 96 tests passed, 1 Redis availability test skipped |
| `make dist` | Passed: wheel and sdist built, `twine check dist/*` passed |
| `make e2e` | Passed: Docker app + Redis stack, 13 e2e tests passed |
| PyPI name check | `falcon-rate-limiter` returned HTTP 404 from PyPI JSON API on 2026-06-09 |

Readiness fixes applied during this inspection:

| Area | Change |
|---|---|
| CI e2e | `.github/workflows/ci.yml` now runs `make e2e` in the e2e job instead of only installing e2e dependencies |
| Packaging | `pyproject.toml` now uses modern SPDX-style license metadata and no longer emits setuptools license deprecation warnings during build |
| Import package | Renamed the import package from `limiter` to `falcon_rate_limiter` to avoid collisions with the existing PyPI `limiter` project |
| Public API | `get_remote_address` is exported from `falcon_rate_limiter` and documented |
| Cleanup | Tracked `.pyc` files under `tests/e2e/__pycache__/` were removed from Git |
| Ignore rules | `.gitignore` now ignores `__pycache__/` and `*.py[cod]` recursively |
| Compose | Removed obsolete top-level `version` from `tests/e2e/docker-compose.yml` |

## Serious Items Left

| Severity | Item | Recommendation |
|---|---|---|
| Low | The sdist includes unit tests. The wheel only includes the package. | This is acceptable. If you want a smaller sdist, add explicit manifest rules later. |

No runtime release blocker was found in the tested package path.

## Public GitHub Steps

Before changing visibility, inspect committed history for secrets. Deleting a secret from the latest tree is not enough if it exists in Git history.

```bash
git grep -n -I -E '(token|secret|password|api[_-]?key|pypi|redis://[^[:space:]]+:[^[:space:]@]+@)' HEAD
git log --all --name-only --pretty=format: | sort -u | grep -Ei '(^|/)(\\.env|.*secret.*|.*token.*|.*key.*)$' || true
gh secret list --repo w7089/falcon-rate-limiter
```

Make the repository public with GitHub CLI:

```bash
gh auth status
gh repo view w7089/falcon-rate-limiter --json nameWithOwner,visibility,url
gh repo edit w7089/falcon-rate-limiter --visibility public --accept-visibility-change-consequences
gh repo view w7089/falcon-rate-limiter --json nameWithOwner,visibility,url
```

Optional public repo metadata:

```bash
gh repo edit w7089/falcon-rate-limiter \
  --description "Rate limiting for Falcon applications powered by limits." \
  --homepage "https://pypi.org/project/falcon-rate-limiter/" \
  --enable-issues \
  --enable-squash-merge \
  --delete-branch-on-merge \
  --add-topic falcon \
  --add-topic rate-limiting \
  --add-topic python \
  --add-topic limits
```

Alternative UI path: GitHub repository page -> Settings -> Danger Zone -> Change repository visibility -> Public.

GitHub visibility consequences to account for:

| Consequence | Impact |
|---|---|
| Code visibility | The repository code becomes visible to everyone. |
| Forking | Anyone can fork the repository. |
| Actions logs | Actions history and logs become visible. |
| Activity | Changes become public activity. |
| Rulesets | Push rulesets can be disabled when changing private to public. Recheck branch protections afterward. |

## PyPI Trusted Publishing Setup

Use PyPI Trusted Publishing rather than a long-lived PyPI API token. The existing `.github/workflows/publish.yml` is already structured for this:

| Workflow setting | Current value |
|---|---|
| Trigger | Pushing tags matching `v*.*.*` |
| Publish environment | `pypi` |
| OIDC permission | `id-token: write` |
| Publish action | `pypa/gh-action-pypi-publish@release/v1` |

For the first release, create a pending publisher on PyPI before pushing the tag:

| PyPI field | Value |
|---|---|
| Project name | `falcon-rate-limiter` |
| Owner | `w7089` |
| Repository name | `falcon-rate-limiter` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

Recommended GitHub environment setup:

1. Open GitHub repo Settings -> Environments.
2. Create environment `pypi`.
3. Add yourself as a required reviewer before the first real release.

PyPI pending publishers do not reserve a project name until the first successful upload. Recheck the name immediately before tagging:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/falcon-rate-limiter/json
```

Expected result before first release: `404`.

## First PyPI Release Commands

Use these commands once the repository is public, PyPI pending publisher is configured, and you have committed the readiness changes.

```bash
make check
make dist
make e2e
git status --short
```

For a first release using the current `0.1.0` version:

```bash
git rm -f tests/e2e/__pycache__/*.pyc
git add .github/workflows/ci.yml .gitignore pyproject.toml README.md limiter tests tests/e2e/docker-compose.yml PUBLICATION_READINESS.md
git commit -m "chore: prepare public release"
git branch --show-current
```

If the current branch is not `main`, push the branch, open a PR, and merge it before tagging. Then tag from the updated `main` branch:

```bash
git switch main
git pull --ff-only
make release-tag
git push origin v0.1.0
```

If `v0.1.0` already exists or you want to publish a new patch release:

```bash
make release
$EDITOR CHANGELOG.md
make check
make dist
make e2e
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release $(make version)"
git switch main
git pull --ff-only
make release-tag
git push origin "v$(make version)"
```

Watch the release:

```bash
gh run list --workflow publish.yml --limit 5
gh run watch
```

Verify installation after PyPI publishes:

```bash
python -m venv /tmp/falcon-rate-limiter-install-check
/tmp/falcon-rate-limiter-install-check/bin/python -m pip install --upgrade pip
/tmp/falcon-rate-limiter-install-check/bin/python -m pip install falcon-rate-limiter
/tmp/falcon-rate-limiter-install-check/bin/python - <<'PY'
from falcon_rate_limiter import FalconRateLimiter, FalconRateLimitMiddleware, get_remote_address

print(FalconRateLimiter)
print(FalconRateLimitMiddleware)
print(get_remote_address)
PY
```

## Files And Folders To Keep Out Of The Public Repo

Already fixed in Git:

| Path | Status |
|---|---|
| `tests/e2e/__pycache__/*.pyc` | Removed from tracking |
| `__pycache__/`, `*.py[cod]` | Ignored recursively |

Do not commit these generated/local folders:

```text
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.repotomcp/
build/
dist/
falcon_rate_limiter.egg-info/
**/__pycache__/
```

Local-only planning material:

```text
plan/
```

`plan/` is currently ignored and not tracked. Keep it local if it is useful. `plan/todo-features.md` and `plan/implementation-plan.md` have been updated to keep `enabled`, environment configuration, and `swallow_errors` visible as planned work rather than shipped features.

Optional public-polish review:

| Path | Recommendation |
|---|---|
| `AGENTS.md` | Tracked. Keep if you want AI-agent contributor guidance public; remove if you prefer a conventional public repo. |
| `.github/copilot-instructions.md` | Tracked. Keep if you want Copilot guidance public. |
| `blog/` | Tracked. Keep if these posts are intended as public launch/marketing content; otherwise move them out before public release. |

No `logs/` directory was found.

Cleanup command for local-only generated artifacts:

```bash
rm -rf .venv .pytest_cache .mypy_cache .ruff_cache .repotomcp build dist falcon_rate_limiter.egg-info falcon_rate_limiter/__pycache__ tests/__pycache__ tests/e2e/__pycache__
```

Do not run that command if you want to keep the local virtualenv or current build artifacts.

## Plan And MVP Review

MVP goals are broadly complete:

| Goal | Status |
|---|---|
| Falcon route examples | Done |
| Decorator-based fixed-window limiter | Done |
| `limits` integration | Done |
| In-memory storage | Done |
| Redis storage path | Done and covered by e2e |
| Async/ASGI behavior | Covered in unit tests |
| Documentation and examples | README and `examples/quick_start.py` exist |
| CI/CD | Present, and e2e now actually runs on `main` pushes |

Plan accuracy issues:

| File | Issue |
|---|---|
| `plan/mvp-plan.md` | Mostly historical learning goals; fine to keep private, not useful as public roadmap. |
| `plan/implementation-plan.md` | Updated current implementation plan; Phase 6 now marks `enabled`, environment config, `swallow_errors`, and rate-limit-exceeded logging as planned work. |
| `plan/todo-features.md` | Updated current internal backlog; keep private unless you want to publish roadmap-style planning docs. |

Features not implemented but not currently advertised as shipped:

| Feature | Release impact |
|---|---|
| `enabled=False` | Useful, but not required for alpha if undocumented. |
| Environment variable configuration | Useful for deployment parity with slowapi, but not required for alpha if undocumented. |
| `swallow_errors` | Operationally useful, but fallback already exists for storage failures. |
| String limit syntax such as `"5/minute"` | Nice-to-have slowapi parity; current explicit `requests` + `relativedelta` API is documented. |
| Multiple limits in one decorator | Nice-to-have; stacking decorators and shared limits cover many cases. |
| Application-wide shared limits | Nice-to-have; not currently advertised. |
| Custom error handler hook | Nice-to-have; custom error message exists. |
| `key_prefix` | Useful for multi-app shared storage; not required for first alpha. |

Recommended release stance: publish as `0.1.0` alpha only after deciding the import package name. Keep unsupported features out of README, PyPI description, and release notes.

## E2E Testing

The e2e suite is functional.

| Area | Details |
|---|---|
| Stack | Docker Compose starts Redis and a Gunicorn-served Falcon app from `tests/e2e/app/app.py`. |
| App port | Host `localhost:8765`, container `8080`. |
| Health check | `make e2e-up` waits for the app health check before tests run. |
| Test isolation | Each test uses a unique `X-Test-Client-Id` to avoid shared counters. |
| Coverage | Health, allowed requests, 429 responses, rate-limit headers, custom errors, client isolation, middleware default limits, exemptions, and Redis-backed limits. |
| Local command | `make e2e` |
| Manual command split | `make e2e-up`, `make test-e2e`, `make e2e-down` |

CI behavior after the readiness fix:

| Event | E2E behavior |
|---|---|
| Pull request | Does not run Docker e2e. Runs lint, mypy, unit tests, and package build. |
| Push to `main` | Runs e2e after the `check` job. |
| Release tag `vX.Y.Z` | Publish workflow runs release e2e before building and publishing. |

`pytest` ignores `tests/e2e` by default through `pyproject.toml`, so ordinary `make test` stays fast and does not require Docker.

## Sources Checked

Official/current publishing references:

| Topic | Source |
|---|---|
| PyPI Trusted Publishing overview | https://docs.pypi.org/trusted-publishers/ |
| PyPI pending publisher for first project creation | https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/ |
| PyPI publisher fields for existing projects | https://docs.pypi.org/trusted-publishers/adding-a-publisher/ |
| GitHub repository visibility consequences and UI path | https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility |
| GitHub CLI `gh repo edit --visibility` | https://cli.github.com/manual/gh_repo_edit |
| Distribution package vs import package naming | https://packaging.python.org/en/latest/discussions/distribution-package-vs-import-package/ |
| PyPA distribution name normalization | https://packaging.python.org/en/latest/specifications/name-normalization/ |
| Existing PyPI `limiter` project | https://pypi.org/project/limiter/ |
