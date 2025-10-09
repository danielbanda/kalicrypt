# RP5 Provisioner Logging

- Primary JSONL command log: `/home/admin/rp5/03_LOGS/ete_nvme.jsonl` (fallbacks `/var/log/rp5/ete_nvme.jsonl`, `/tmp/rp5-logs/ete_nvme.jsonl`).
- Resolver prints `log_path=<path>` on startup and all command traces append to the same file.
- Each entry emitted by `executil.run()` includes `{ ts, kind: exec|done, cmd[], rc, dur, out, err }` along with TRACE events.
- Result JSON objects and timing metadata are appended to this log for downstream consumption.
