# RP5 Provisioner Logging
- JSONL command log: `/var/log/rp5/ete_nvme.jsonl` (fallback `/tmp/rp5-logs/ete_nvme.jsonl`).
- Each entry: { ts, kind:exec|done, cmd[], rc, dur, out, err }.
- Collected automatically by `executil.run()`.
