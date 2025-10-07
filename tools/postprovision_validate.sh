#!/usr/bin/env bash
set -euo pipefail

# Colors
g="\033[0;32m"; y="\033[0;33m"; r="\033[0;31m"; n="\033[0m"
ok(){ echo -e "${g}[OK]${n} $*"; }
warn(){ echo -e "${y}[WARN]${n} $*"; }
fail(){ echo -e "${r}[FAIL]${n} $*"; exit 1; }

# Usage: run on the live system AFTER provisioning, with the target root mounted (default /mnt/nvme)
MNT="${1:-/mnt/nvme}"
ESP="${MNT}/boot/firmware"
# Device defaults (used in hints and lookups)
NVME_DEV="${NVME_DEV:-/dev/nvme0n1}"
P1="${P1:-${NVME_DEV}p1}"
P2="${P2:-${NVME_DEV}p2}"
P3="${P3:-${NVME_DEV}p3}"


# ===== TRACE SECTION =====
set -x
echo "whoami: $(whoami)"; id
echo "date: $(date -Is)"
echo "MNT=${MNT}  ESP=${ESP}"
echo "findmnt of MNT:"

# # ===== MOUNTPOINT CHECK =====
if ! findmnt -no SOURCE,TARGET "${MNT}" >/dev/null 2>&1 || [ -z "$(findmnt -no SOURCE "${MNT}" 2>/dev/null)" ]; then
  echo "[FAIL] ${MNT} is not a mountpoint (target root not mounted)."
    echo "Attempting auto-mount (using ~/rp5/tools/mount_target_root.sh)..." 
  AUTOKEY="${KEYFILE:-}"; if [ -z "$AUTOKEY" ]; then if [ -n "${SUDO_USER:-}" ] && [ -d "/home/${SUDO_USER}" ]; then AUTOKEY="/home/${SUDO_USER}/secret.txt"; else AUTOKEY="$HOME/secret.txt"; fi; fi
  if command -v cryptsetup >/dev/null 2>&1; then
    KEYFILE="$AUTOKEY" bash "$HOME/rp5/tools/mount_target_root.sh" "${MNT}" || true
  fi
  if findmnt -no SOURCE "${MNT}" >/dev/null 2>&1; then
    echo "[OK] Auto-mount succeeded: $(findmnt -no SOURCE,TARGET ${MNT})"
  else
    echo "Hint: open and mount the target root, then re-run:"
    echo "  cryptsetup open UUID=$(blkid -s UUID -o value ${P3}) cryptroot --key-file ~/secret.txt --allow-discards"
    echo "  vgchange -ay rp5vg; mount /dev/mapper/rp5vg-root ${MNT}"
    echo "OR just run: sudo bash ~/rp5/tools/mount_target_root.sh ${MNT}"
    exit 2
  fi
fi
# ============================
=== MOUNTPOINT CHECK =====
if ! findmnt -no SOURCE,TARGET "${MNT}" >/dev/null 2>&1 || [ -z "$(findmnt -no SOURCE "${MNT}" 2>/dev/null)" ]; then
  echo "[FAIL] ${MNT} is not a mountpoint (target root not mounted)."
    echo "Attempting auto-mount (using ~/rp5/tools/mount_target_root.sh)..." 
  AUTOKEY="${KEYFILE:-}"; if [ -z "$AUTOKEY" ]; then if [ -n "${SUDO_USER:-}" ] && [ -d "/home/${SUDO_USER}" ]; then AUTOKEY="/home/${SUDO_USER}/secret.txt"; else AUTOKEY="$HOME/secret.txt"; fi; fi
  if command -v cryptsetup >/dev/null 2>&1; then
    KEYFILE="$AUTOKEY" bash "$HOME/rp5/tools/mount_target_root.sh" "${MNT}" || true
  fi
  if findmnt -no SOURCE "${MNT}" >/dev/null 2>&1; then
    echo "[OK] Auto-mount succeeded: $(findmnt -no SOURCE,TARGET ${MNT})"
  else
    echo "Hint: open and mount the target root, then re-run:"
    echo "  cryptsetup open UUID=$(blkid -s UUID -o value ${P3}) cryptroot --key-file ~/secret.txt --allow-discards"
    echo "  vgchange -ay rp5vg; mount /dev/mapper/rp5vg-root ${MNT}"
    echo "OR just run: sudo bash ~/rp5/tools/mount_target_root.sh ${MNT}"
    exit 2
  fi
fi
# ============================
findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS "${MNT}" || true
echo "findmnt of ESP (if present):"
findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS "${ESP}" || true
echo "ls -l of crypttab:"
ls -l "${MNT}/etc/crypttab" || true
echo "stat -c '%U:%G %a %s %y' crypttab:"
stat -c '%U:%G %a %s %y' "${MNT}/etc/crypttab" 2>/dev/null || true
echo "head -n 10 crypttab (showing special chars):"
tr -c '[:print:]\n\t' '?' < "${MNT}/etc/crypttab" 2>/dev/null | sed -n '1,10p' || true
echo "source host /etc/crypttab head (for context):"
tr -c '[:print:]\n\t' '?' < /etc/crypttab 2>/dev/null | sed -n '1,10p' || true
# =========================

[ -d "$MNT" ] || fail "Target root mount not found: $MNT"
[ -e "$ESP" ] || warn "ESP not found at $ESP (continuing)"

# 1) Identify partitions (best-effort; adjust if needed)

# 2) Collect UUIDs
p1_uuid="$(blkid -s UUID -o value "$P1" || true)"
p2_uuid="$(blkid -s UUID -o value "$P2" || true)"
luks_uuid="$(blkid -s UUID -o value "$P3" || true)"

[ -n "${p1_uuid:-}" ] && ok "P1 UUID: $p1_uuid" || warn "P1 UUID missing"
[ -n "${p2_uuid:-}" ] && ok "P2 UUID: $p2_uuid" || warn "P2 UUID missing"
[ -n "${luks_uuid:-}" ] && ok "LUKS UUID: $luks_uuid" || warn "LUKS UUID missing"

# 3) /etc/crypttab
crypttab="${MNT}/etc/crypttab"
if [ -s "$crypttab" ]; then
  line="$(grep -E '^[[:space:]]*cryptroot[[:space:]]+' "$crypttab" || true)"
  if echo "$line" | grep -q "UUID=${luks_uuid}"; then
  ok "crypttab UUID matches LUKS UUID"
else
  echo "Offending crypttab line: ${line:-<empty>}"
  echo "=== crypttab content (head) ==="
  sed -n "1,50p" "$crypttab"
  echo "=== crypttab tail ==="
  tail -n 50 "$crypttab"
  fail "crypttab does not reference LUKS UUID"
fi
  echo "$line" | grep -q "keyscript=" && warn "crypttab contains keyscript= (TPM not enabled by default)"
else
  fail "crypttab missing or empty"
fi

# 4) /boot/firmware/cmdline.txt
if [ -s "${ESP}/cmdline.txt" ]; then
  cmd="$(cat "${ESP}/cmdline.txt")"
  echo "$cmd" | grep -q "root=/dev/mapper/rp5vg-root" && ok "cmdline root mapper is rp5vg-root" || fail "cmdline root mapper not set to rp5vg-root"
  echo "$cmd" | grep -q "cryptdevice=UUID=${luks_uuid}:cryptroot" && ok "cmdline cryptdevice UUID matches" || fail "cmdline cryptdevice UUID mismatch"
else
  fail "cmdline.txt missing"
fi

# 5) /etc/fstab
fstab="${MNT}/etc/fstab"
if [ -s "$fstab" ]; then
  grep -q "UUID=${p1_uuid}.*\\s/boot/firmware\\s" "$fstab" && ok "fstab P1 -> /boot/firmware" || fail "fstab lacks P1 for /boot/firmware"
  grep -q "UUID=${p2_uuid}.*\\s/boot\\s" "$fstab" && ok "fstab P2 -> /boot" || fail "fstab lacks P2 for /boot"
  grep -q "/dev/mapper/rp5vg-root\\s/\\s" "$fstab" && ok "fstab root -> rp5vg-root" || fail "fstab missing root mapping"
else
  fail "fstab missing or empty"
fi

# 6) initramfs presence & contents
cfg="${ESP}/config.txt"
if [ -s "$cfg" ]; then
  line="$(grep -E '^initramfs\\s+\\S+\\s+followkernel' "$cfg" || true)"
  img="$(echo "$line" | awk '{print $2}')"
  [ -n "$img" ] || fail "config.txt missing initramfs line"
  [ -s "${ESP}/${img}" ] || fail "initramfs image missing: ${ESP}/${img}"
  if command -v lsinitramfs >/dev/null 2>&1; then
    out="$(lsinitramfs "${ESP}/${img}" | awk 'NR<1e6{print}')" || true
    echo "$out" | grep -q '/sbin/cryptsetup' && ok "initramfs contains cryptsetup" || fail "initramfs missing cryptsetup"
    echo "$out" | grep -q '/sbin/lvm' && ok "initramfs contains lvm" || fail "initramfs missing lvm"
  else
    warn "lsinitramfs not found; skipping image contents check"
  fi
else
  fail "config.txt missing"
fi

# 7) Recovery doc & postboot check
[ -x "${MNT}/usr/local/sbin/rp5-postboot-check" ] && ok "postboot-check installed" || warn "postboot-check not found"
if [ -s "${MNT}/root/RP5_RECOVERY.md" ]; then
  grep -q "UUID=${luks_uuid}" "${MNT}/root/RP5_RECOVERY.md" && ok "recovery doc references LUKS UUID" || warn "recovery doc UUID mismatch"
else
  warn "recovery doc not found"
fi

# 8) Optional: validate LUKS header label
if command -v cryptsetup >/dev/null 2>&1; then
  if cryptsetup luksDump "$P3" | grep -q 'label: *rp5root'; then
    ok "LUKS label is rp5root"
  else
    warn "LUKS label not 'rp5root' (non-blocking)"
  fi
fi

echo -e "${g}RESULT:${n} POSTPROVISION_VALIDATION_OK"
