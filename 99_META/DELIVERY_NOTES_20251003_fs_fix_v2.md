# Delivery Notes — 2025-10-03

- Fixed AttributeError: use `run(...).out` instead of `.stdout`.
- `_ensure_fs` is now idempotent and relies on `executil.run` interface:
  - Skip format when TYPE matches and (optional) LABEL matches.
  - For ext4 label drift, use `e2label` instead of reformat.
  - For vfat label drift, try `dosfslabel`/`fatlabel` before mkfs.
