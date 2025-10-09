# Contributing to RP5

Thanks for contributing! This repository uses GitHub Actions for CI and a few lightweight rules to keep quality high without slowing iteration.

## Quick start

- Run the linters and tests locally:
  - `pre-commit install && pre-commit run -a`
  - `pytest -q --maxfail=1`

- Open a PR to `main`. CI will run:
  - Ruff + Black + Codespell
  - Mypy
  - Pytest + coverage (fail under 85% total)

## Branch protection (temporarily relaxed)

To simplify iteration right now, we **do not** enforce:
- Required PR reviews or dismissal of stale approvals.
- Linear history / squash-only, and we **do not** block direct pushes.

**Re-enable later (checklist):**
1. Settings → Branches → `main` rule → enable “Require a pull request before merging”.
2. Require 1–2 approvals and “Dismiss stale approvals on new commits”.
3. Enable “Require linear history” (and optionally “Require branches to be up to date”).

## CI caching

This repo uses `ci/requirements-dev.txt` as the cache key for pip caches in CI.
- If you add or update dev tools, update that file so caching stays effective.
- If you later add a top-level `pyproject.toml`/`requirements.txt`, you can remove `cache-dependency-path` from workflows.

## Security

- CodeQL scanning is enabled.
- Dependabot is configured for `pip` and GitHub Actions.
- Do **not** commit secrets. Tests should mock privileged calls.

## Coverage

We aim for 85% overall, with a focus on critical modules:
`provision/cli.py`, `initramfs.py`, `postcheck.py`, `root_sync.py`, `safety.py`.
