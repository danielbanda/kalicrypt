# RP5 NVMe Boot Expectations (Raspberry Pi 5)

This documents the **post-provision, pre-reboot** state required for a flawless NVMe boot with LUKS+LVM on Pi 5.

## ESP (FAT, `/dev/nvme0n1p1` → `/boot/firmware`)

- `bcm2712-rpi-5-b.dtb` present.
- `overlays/` populated (non-empty).
- `vmlinuz` present (unversioned kernel image; we prefer the Pi 5 flavor `*-rpi-2712`).
- `initramfs_2712` **and/or** `initramfs8` present.
- `config.txt` MUST contain these lines (case-insensitive):
  - `device_tree=bcm2712-rpi-5-b.dtb`
  - `os_check=0`
  - `kernel=vmlinuz`
  - An initramfs line using **followkernel**, either:
    - `initramfs initramfs followkernel` *(normalized base name)*, or
    - `initramfs initramfs_2712 followkernel` *(explicit Pi 5 image)*

## Kernel command line (`/boot/firmware/cmdline.txt` on ESP)

Must include:
- `cryptdevice=UUID=<UUID-of-/dev/nvme0n1p3>:cryptroot`
- `root=/dev/mapper/rp5vg-root`
- `rootfstype=ext4`
- `rootwait`

The `<UUID-of-/dev/nvme0n1p3>` is obtained from `blkid -s UUID -o value /dev/nvme0n1p3`.

## Optional rootfs validations

If you unlock LUKS and mount root:
- `/etc/fstab` declares `/` via `/dev/mapper/rp5vg-root`
- `/etc/crypttab` declares the `cryptroot` mapping

## Tools

- **Postcheck script**: `provision/ete_postcheck.sh` (idempotent, Pi 5 hardened)
- **Quick verifier**: `provision/ete_quick_verify.py`

## Notes

- Pi firmware loads **kernel** and **device tree** directly from the ESP. That’s why `vmlinuz` and `bcm2712-rpi-5-b.dtb` must live on the ESP.
- Using `followkernel` keeps initramfs aligned with the selected kernel.
- If you see bootloader complaints about unsupported OS or missing DTB, re-copy `bcm2712-rpi-5-b.dtb`, populate `overlays/`, and ensure `os_check=0` in `config.txt`.
