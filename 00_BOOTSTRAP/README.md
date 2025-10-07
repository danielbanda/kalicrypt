# vNext Bundle

This bundle contains:
- `docs/instructions/global-style.md` — the single source of truth for global style/workflow
- `docs/projects/RP5/rules.md` — project‑level overrides example
- `tools/prompt_lint.py` — a simple linter for instruction files

## Quick Start

1) Adopt `docs/instructions/global-style.md` as your global source of truth.
2) Keep project overrides under `docs/projects/<name>/rules.md`.
3) Run the linter against your instruction folders:

```bash
python3 tools/prompt_lint.py --root docs --sections "Purpose,Style & Tone,Freshness & Web Use,Code & Artifacts (General),Project-Level Overrides,Automations,Memory,Safety & Refusals,Structured Output Defaults,Precedence (Conflict Resolution)"
```

The linter will:
- Flag banned phrases
- Check for required sections
- Print a compact report with exit code 0 (clean) or 1 (issues found)

## Provisioning
See `docs/usage/provisioning.md` for the canonical entrypoint and command examples.

