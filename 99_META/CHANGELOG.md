# RP5 Provisioner – Change Log

## 2025-10-02 — Phase 2.4
- executil: added structured JSONL logging (`/var/log/rp5/ete_nvme.jsonl` fallback `/tmp/rp5-logs/`).
- luks_lvm: `format_luks` skips if already LUKS; now forces with `--force --label rp5root`.
- luks_lvm: `open_luks` skips if mapper already exists.
- logging shows each command + rc/out/err/duration.

## 2025-10-02 — Phase 2.3
- luks_lvm: switched to non-interactive cryptsetup calls (`--batch-mode --key-file`).
- Fixed PV/VG/LV order (`pvcreate` → `vgcreate` → `lvcreate`).

## 2025-10-02 — Phase 2.2
- partitioning: stronger reread gates (`blockdev --rereadpt`, `partx`, `hdparm -z`).
- Fallback to `parted` if `sgdisk` fails.
- Holder killer++ and base-device guard.

## 2025-10-02 — Phase 2.1
- executil: added timeout and retry for long-running commands.
- partitioning: aggressive pre-cleanup, `wipefs`, settle+retry.

## 2025-10-02 — Phase 2
- firmware/boot_plumbing/initramfs/postcheck modules introduced.
- cli: full-run path implemented.

## 2025-10-02 — Phase 1
- devices/partitioning/luks_lvm/mounts modules extracted.
- cli: `--plan` prints step sequence.

## 2025-10-02 — Phase 0
- executil/model/errors modules extracted.
- cli: parses flags, prints structured plan.

## 20251002_215844
- Full-run default + safety rails; docs updated.

## 20251002_225009
- Docs updated; os-import scoping fix; cryptsetup flag fix; packaging rules reaffirmed.

## 20251003_001658
- Docs: central provisioning guide; references updated.
