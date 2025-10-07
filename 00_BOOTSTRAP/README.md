# vNext Bundle

This bundle contains:
- `docs/instructions/global-style.md` — the single source of truth for global style/workflow
- `docs/projects/RP5/rules.md` — project‑level overrides
- `tools/prompt_lint.py` — a simple linter for instruction files

## Quick Start

1) Adopt `docs/instructions/global-style.md` as your global source of truth.
2) Keep project overrides under `docs/projects/<name>/rules.md`.

## Provisioning
See `docs/usage/provisioning.md` for the canonical entrypoint and command examples.

## Ongoing Log Instructions
* **Log Format**: Append each entry to `01_DOCS/ongoing_log.md`.
* **Each Entry Should Include**:
    1. **Timestamp** (e.g. `2025-10-01T23:45`)
    2. **Author or Source** (e.g. `Daniel`, `ChatGPT`)
    3. **Summary** of change, issue, or insight
    4. **Reasoning** behind the decision or observation
    5. **Linked Artifact** or file reference (if applicable)
* **When to Add Entries**:
    * After each significant script update or run
    * When a bug or issue is observed (even if unresolved)
    * When a workaround or fix is applied
    * When a new safeguard, check, or validation is added
    * When assumptions change or new constraints arise
* **Retention Policy**: Never delete entries. If something is obsolete, mark it clearly (e.g. `~~deprecated~~` or `OUTDATED:`), but preserve history.
* **Inclusion in Artifacts**: This log must be bundled in every project tarball/checkpoint under `/01_DOCS/ongoing_log.md` or equivalent path.
