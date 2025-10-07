# RP5 Quickstart Prompt (Pinned Canonical)

Goal: Make NVMe OS provisioning and boot flawless on Pi 5. Entry point is `rp5/provision/cli.py`.

What to do on each session:
1) Load my latest tar if provided; rehydrate in-memory only.
2) Inspect `rp5/provision/*`, confirm entrypoint & flags, and list any gaps that block an end-to-end, idempotent run.
3) Propose minimal, concrete next steps (no code unless asked), focusing on: plan/dry-run JSON, safety rails (same-disk checks), rsync correctness, firmware/cmdline/initramfs verification, post-boot heartbeat, and logging/RESULT codes.
4) Keep replies concise; structure as:
   - Rehydrate summary
   - Blocking gaps
   - Next steps
   - Sanity commands

House rules:
- Don’t emit scripts or large inline code unless I explicitly request a tar.
- Treat TPM work as deferred; ignore `--tpm-keyscript` unless explicitly enabled.
- Use idempotent, belt-and-suspenders, RESULT markers

Output format every time:
- “Rehydrate summary” (paths, SHA prefix, entrypoint, flags)
- “Blocking gaps” (numbered, crisp)
- “Next steps” (ordered, minimal)
- “Sanity commands” (read-only first)

---

# Next Steps Policy

- `NEXT_STEPS.md` files record tactical, evolving tasks for RP5 engineering.
- The **RP5 quickstart prompt** above remains pinned and canonical; it must not be replaced or lost.
- On every iteration, new `next_steps_<timestamp>.md` documents may be added under `01_DOCS/` to track progress.
- `AI_rules.md` persists the quickstart and meta-policies; `NEXT_STEPS.md` evolves with concrete actions.

---
# Project Overrides — RP5

These rules override the global vNext spec for RP5 conversations and artifacts.

## Output & Delivery
- Do **not** emit code or archives unless explicitly requested by the user.
- Provide scripts as files/tarballs rather than long inline dumps.
- Never render more than ~20 lines of code in chat.
- Refer delivering single script -- echo-ing out for verification when needed - over multiple "script" execution to review their output

## Safety & Execution
- Belt‑and‑suspenders safety: strong preflight checks, idempotent behavior.
- Use colored markers [OK]/[WARN]/[FAIL] and a final RESULT line.
- Ask for outputs/logs from user‑run commands to verify.
- Keep canonical project rules separate; project memory contains preferences only. Canonical artifacts are source of truth.

## Packaging
- When asked for a checkpoint tar/zip: include the **entire** project state (initial + new files). No deltas only.
- Use explicit filenames and timestamps.
- Enfornce RP5 Project structure (top-level)
 - 00_BOOTSTRAP
 - 01_DOCS
 - 03_LOGS
 - 04_ARTIFACTS
 - 99_META
 - docs
 - provision
 - tools

## Freshness & Citations
- Follow the global browsing and citation policy, but prefer local project artifacts over the web when applicable.