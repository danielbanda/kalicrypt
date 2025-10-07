# Cryptsetup Troubleshooting (RP5)

- Ensure kernel modules: `dm_mod`, `dm_crypt`, `cryptd` are loaded (`modprobe` if needed).
- If `luksFormat` fails, wipe signatures on the target partition and retry:
  - `wipefs -a /dev/<devpX>` then `blkdiscard -f /dev/<devpX>` (or zero first 16 MiB).
- Avoid non-portable flags (`--force`) on older cryptsetup versions.
- Verify keyfile path and permissions; avoid empty files.
- Use `cryptsetup -v ...` for verbose errors.
