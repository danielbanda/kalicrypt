#!/usr/bin/env bash
# ete_postcheck.sh — RP5 NVMe boot postcheck (Pi 5 hardened)
# Idempotent, fail-fast; verifies ESP + boot args + initramfs + DTB/overlays.
# Usage: sudo bash ete_postcheck.sh

set -euo pipefail
RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; CLR=$'\e[0m'

DEVICE="${DEVICE:-/dev/nvme0n1}"
ESP_DEV="${ESP_DEV:-${DEVICE}p1}"
BOOT_DEV="${BOOT_DEV:-${DEVICE}p2}"
P3_DEV="${P3_DEV:-${DEVICE}p3}"
MNT="${MNT:-/mnt/nvme}"
BOOT="${BOOT:-$MNT/boot}"
ESP="${ESP:-$BOOT/firmware}"

say() { printf '%b\n' "$*"; }
ok()  { printf '%b\n' "${GRN}[OK]${CLR} $*"; }
fail(){ printf '%b\n' "${RED}[FAIL]${CLR} $*"; return 1; }

mounted() { findmnt -n "$1" >/dev/null 2>&1; }

ensure_mount() {
  local dev="$1" mnt="$2"
  mkdir -p "$mnt"
  mounted "$mnt" || mount "$dev" "$mnt" || true
  mounted "$mnt" && ok "mounted $dev -> $mnt" || fail "mount $dev -> $mnt"
}

umount_safe() {
  local p="$1"
  mounted "$p" || return 0
  umount "$p" || true
  mounted "$p" && { fuser -km "$p" || true; umount -l "$p" || true; }
  mounted "$p" && fail "umount $p" || ok "umounted $p"
}

blk_uuid() { blkid -s UUID -o value "$1" 2>/dev/null || true; }

main() {
  ensure_mount "$BOOT_DEV" "$BOOT"
  ensure_mount "$ESP_DEV"  "$ESP"

  local ok_all=0

  # 1) Core ESP assets
  [[ -f "$ESP/bcm2712-rpi-5-b.dtb" ]] && ok "DTB present" || { fail "DTB missing: bcm2712-rpi-5-b.dtb"; ok_all=1; }
  [[ -s "$ESP/vmlinuz" ]] && ok "kernel present on ESP (vmlinuz)" || { fail "kernel vmlinuz missing on ESP"; ok_all=1; }
  [[ -d "$ESP/overlays" && -n "$(ls -A "$ESP/overlays" 2>/dev/null)" ]] && ok "overlays present" || { fail "overlays directory is empty"; ok_all=1; }

  # 2) config.txt expectations
  local cfg="$ESP/config.txt"
  [[ -f "$cfg" ]] || { fail "config.txt missing"; ok_all=1; }
  local cfg_txt; cfg_txt="$(tr -d '\r' <"$cfg" || true)"
  grep -qi '^device_tree=bcm2712-rpi-5-b.dtb' <<<"$cfg_txt" && ok "device_tree set to Pi 5 DTB" || { fail "device_tree=bcm2712-rpi-5-b.dtb missing"; ok_all=1; }
  grep -qi '^os_check=0' <<<"$cfg_txt" && ok "os_check=0 present" || { fail "os_check=0 missing"; ok_all=1; }
  grep -qi '^kernel=vmlinuz' <<<"$cfg_txt" && ok "kernel=vmlinuz present" || { fail "kernel=vmlinuz missing"; ok_all=1; }
  # Accept either normalized base or explicit _2712; must include followkernel
  if grep -qi '^initramfs initramfs\(_2712\)\? followkernel' <<<"$cfg_txt"; then
    ok "initramfs ... followkernel present (base or _2712)"
  else
    fail "initramfs line missing or lacks followkernel"; ok_all=1
  fi

  # 3) cmdline.txt expectations
  local cmd="$ESP/cmdline.txt"
  [[ -f "$cmd" ]] || { fail "cmdline.txt missing"; ok_all=1; }
  local cmdtxt; cmdtxt="$(tr -d '\n\r' <"$cmd" || true)"
  local uuid_p3; uuid_p3="$(blk_uuid "$P3_DEV")"
  grep -q 'root=/dev/mapper/rp5vg-root' <<<"$cmdtxt" && ok "cmdline root mapper correct" || { fail "cmdline root mapper missing"; ok_all=1; }
  grep -q 'rootfstype=ext4' <<<"$cmdtxt" && ok "rootfstype=ext4 present" || { fail "rootfstype=ext4 missing"; ok_all=1; }
  grep -q 'rootwait' <<<"$cmdtxt" && ok "rootwait present" || { fail "rootwait missing"; ok_all=1; }
  if [[ -n "$uuid_p3" ]]; then
    grep -q "cryptdevice=UUID=${uuid_p3}:cryptroot" <<<"$cmdtxt" && ok "cryptdevice UUID matches p3" || { fail "cryptdevice UUID does not match p3"; ok_all=1; }
  else
    grep -q 'cryptdevice=UUID=' <<<"$cmdtxt" && ok "cryptdevice present (UUID unknown)" || { fail "cryptdevice directive missing"; ok_all=1; }
  fi

  # 4) initramfs content check
  if lsinitramfs "$ESP/initramfs_2712" >/dev/null 2>&1 || lsinitramfs "$ESP/initramfs8" >/dev/null 2>&1; then
    if (lsinitramfs "$ESP/initramfs_2712" 2>/dev/null || true; lsinitramfs "$ESP/initramfs8" 2>/dev/null || true) | egrep -q '(cryptsetup|dm-crypt|lvm|local-top/cryptroot)'; then
      ok "initramfs contains cryptsetup/lvm bits"
    else
      fail "initramfs missing cryptsetup/lvm bits"; ok_all=1
    fi
  else
    fail "initramfs image not found on ESP"; ok_all=1
  fi

  # 5) Summary + exit code
  if [[ "$ok_all" -eq 0 ]]; then
    ok "POSTCHECK_OK"
    echo "RESULT: POSTCHECK_OK"
    exit 0
  else
    fail "POSTCHECK_FAIL"
    echo "RESULT: POSTCHECK_FAIL"
    exit 1
  fi
}

main "$@"
