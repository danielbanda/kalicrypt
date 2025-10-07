# NEXT STEPS (Auto)

1) Use `python3 provision/go.py doctor` and fix any FAIL before proceeding.
2) Provide ISO/IMG input and NVMe device via env or config expected by offline builder; run `go.py ete`.
3) Review logs in `03_LOGS/` and artifacts in `04_ARTIFACTS/`.
4) Migrate remaining `.sh` tools to Python as needed (track in 99_META/ai_ingestion_notes.md).

### ⬆️ 2025-10-07 Append · Boot Verification (Pre-Reboot Guard)

Goal: Validate NVMe LUKS+LVM boot plumbing before reboot to avoid initramfs drops.

Checklist (non-destructive):
1) UUIDs vs cmdline.txt: `blkid` p1/p2/p3, `cryptsetup luksUUID` p3, then grep `cryptdevice=` and `root=/dev/mapper/rp5vg-root` in NVMe ESP cmdline.
2) Initramfs contents: `lsinitramfs .../initramfs_2712 | egrep 'dm|crypt|lvm'` must show crypto/LVM pieces.
3) Files: `crypttab` and `fstab` reference the same UUID and lv path as cmdline.
4) ESP selection: mount NVMe ESP **and** SD ESP (if present); only one may exist and the active one must have the cryptdevice+mapper root line.
5) Initramfs checksum: record `sha256sum initramfs_2712`.
6) Dry-run open/mount: `cryptsetup open`, `vgchange -ay`, mount `/dev/rp5vg/root`, list directories, then cleanly unmount/close.
7) Invariants: cmdline must include `cryptdevice=UUID=...:cryptroot`, `root=/dev/mapper/rp5vg-root`, `rootwait`, and must NOT contain `PARTUUID=`.

Automation: `python -m provision --nvme-verification ...` (new flag) runs all checks and emits `VERIFY_OK` with a JSON block under `verify`.
