# Delivery Notes — 2025-10-03 23:48:05

- Applied idempotent filesystem guard in `provision/mounts.py` (`_ensure_fs`) to avoid reformatting when TYPE and LABEL already match.
- Behavior: if device already matches `fstype` and `label`, do nothing; if only label differs (ext4), use `e2label`; for vfat, try `dosfslabel`/`fatlabel` before mkfs.
- This addresses repeated `mkfs.ext4` attempts during ETE runs on `/dev/rp5vg/root`.
- No other content changes.
- Exclusions preserved for new tarballs: omit `05_CHECKPOINTS/`, `__MACOSX/`, and any `__pycache__/` directories.
