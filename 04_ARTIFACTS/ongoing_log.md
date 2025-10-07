# 📘 `ongoing_log.md` — RP5 ETE Provisioning Log

---

### 🕒 `2025-10-01T09:15` — Intermittent Provision Failures Diagnosed

**Author:** Daniel (via ChatGPT)
**Issue:**

* `cryptroot` device existed unexpectedly
* Mountpoints (`/mnt/nvme/boot`, `/boot/firmware`) missing
* ESP lacked critical Pi firmware (`start4.elf`, `fixup4.dat`)

**Cause:**

1. LVM device-mapper holders blocked `cryptroot` re-init.
2. Premature `mkdir` before parent mountpoints caused overlaying.
3. Firmware packages weren’t present or copied post-chroot.

**Fixes Implemented in Script:**

* Full LV/VG/mapper pre-cleanup: `dmsetup --retry`, deep unmount, swapoff
* Correct mount order: `/` → `/boot` → `/boot/firmware`
* Auto-copy Pi firmware or install fallback via apt
* Patch `config.txt` with correct `initramfs` and `kernel` lines

---

### 🕒 `2025-10-01T10:12` — Provisioner Fully Hydrated

**Author:** rp5 assistant
**Intent:** End-to-end USB → NVMe run with unattended keyfile unlock.
**Changes:**

* Baked-in `KEYFILE_PATTERN`, required `dm`/crypto modules
* Configured `cmdline.txt` with authoritative mapper+UUID
* Installed and verified `initramfs_2712`, firmware, `config.txt`
* Strong [INFO]/[STEP]/[OK] breadcrumbs for stdout clarity
* All logic embedded in ``python -m rp5.provision` (see docs/usage/provisioning.md)`; no external scripts required.

---

### 🕒 `2025-10-01T10:17` — Final Hardening Validated

**Author:** Daniel
**Scope:** Confirm boot success with keyfile unlock on first reboot.
**Validations Now Baked-In:**

* `cmdline.txt` contains:

  ```
  root=/dev/mapper/rp5vg-root cryptdevice=UUID=<LUKS> rootfstype=ext4 rootwait
  ```

* Target `/etc/cryptsetup-initramfs/conf-hook`:
  `KEYFILE_PATTERN="/etc/cryptsetup-keys.d/*"`

* `/etc/initramfs-tools/modules` includes required crypto:
  `dm_mod dm_crypt xts aes_neon_bs sha256_generic`

* `initramfs_2712` is rebuilt inside chroot and placed on ESP

* `/boot/firmware/config.txt` patched with:

  ```
  initramfs initramfs_2712 followkernel
  kernel kernel_2712.img
  ```

---

### 🕒 `2025-10-01T10:25` — Manual + Automated Postcheck Pass

**Author:** Daniel
**Checklist for Audit:**
✅ `cmdline.txt` → correct mapper/crypt lines
✅ `config.txt` → contains `initramfs_2712` + `kernel_2712.img`
✅ `lsinitramfs` → confirms presence of `dm_mod.ko`, `dm-crypt.ko`, `lvm2`, `cryptroot`, `cryptsetup`, and all required AES modules

**Regression Guards:**

* Aggressive cleanup prevents LUKS/VG holder issues
* Mount order avoids hidden folders
* Auto-update fallback in `ete_postcheck.sh` ensures bootable ESP