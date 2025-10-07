#!/usr/bin/env bash
set -euo pipefail

MNT="${1:-/mnt/nvme}"
NVME_DEV="${NVME_DEV:-/dev/nvme0n1}"
P3="${P3:-${NVME_DEV}p3}"

echo "[INFO] Target root mountpoint: $MNT"
echo "[INFO] Using NVME_DEV=$NVME_DEV P3=$P3"

if findmnt -no SOURCE "$MNT" >/dev/null 2>&1; then
  echo "[OK] $MNT already mounted: $(findmnt -no SOURCE,TARGET $MNT)"
  exit 0
fi

if ! command -v cryptsetup >/dev/null 2>&1; then
  echo "[FAIL] cryptsetup not found"; exit 1
fi

L=$(blkid -s UUID -o value "$P3" || true)
if [ -z "${L:-}" ]; then
  echo "[FAIL] Could not read LUKS UUID for $P3"; exit 1
fi

AUTOKEY="${KEYFILE:-}"; if [ -z "$AUTOKEY" ]; then if [ -n "${SUDO_USER:-}" ] && [ -d "/home/${SUDO_USER}" ]; then AUTOKEY="/home/${SUDO_USER}/secret.txt"; else AUTOKEY="$HOME/secret.txt"; fi; fi
if [ ! -r "$AUTOKEY" ]; then
  echo "[FAIL] Keyfile not readable: $AUTOKEY"; echo "[HINT] Set KEYFILE=/path/to/secret.txt"; exit 3; fi
echo "[STEP] Opening LUKS UUID=$L as 'cryptroot' with KEYFILE=$AUTOKEY"
cryptsetup open UUID="$L" cryptroot --key-file "$AUTOKEY" --allow-discards

echo "[STEP] Activating VG rp5vg"
vgchange -ay rp5vg

echo "[STEP] Mounting /dev/mapper/rp5vg-root to $MNT"
mkdir -p "$MNT"
mount /dev/mapper/rp5vg-root "$MNT"

echo "[OK] Mounted: $(findmnt -no SOURCE,TARGET $MNT)"
