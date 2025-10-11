#!/bin/sh
set -eu
RED=$(printf '\033[31m'); GRN=$(printf '\033[32m'); YEL=$(printf '\033[33m'); NC=$(printf '\033[0m')
ok(){ printf "%s[OK]%s %s\n" "$GRN" "$NC" "$*"; }
fail(){ printf "%s[FAIL]%s %s\n" "$RED" "$NC" "$*"; exit 1; }

MNT="${1:-/mnt/nvme}"
ESP="$MNT/boot/firmware"

echo "whoami: $(whoami)"; id; echo "date: $(date -Is)"
echo "MNT=$MNT  ESP=$ESP"
echo "findmnt of MNT:"; findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS "$MNT" || true
echo "findmnt of ESP (if present):"; findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS "$ESP" || true

echo "ls -l of crypttab:"; ls -l "$MNT/etc/crypttab"
echo "stat -c '%U:%G %a %s %y' crypttab:"; stat -c '%U:%G %a %s %y' "$MNT/etc/crypttab"
echo "head -n 10 crypttab (showing special chars):"; sed -n '1,10p' "$MNT/etc/crypttab" | tr -c '[:print:]\n\t' '?'

# Devices & IDs
DISK=$(lsblk -no pkname "$(findmnt -no SOURCE "$MNT" 2>/dev/null || echo /dev/mapper/rp5vg-root)" 2>/dev/null || true)
[ -n "$DISK" ] && P1_DEV="/dev/${DISK}p1" && P2_DEV="/dev/${DISK}p2" || { P1_DEV="/dev/nvme0n1p1"; P2_DEV="/dev/nvme0n1p2"; }
P1_UUID=$(blkid -s UUID -o value "$P1_DEV" 2>/dev/null || true)
P2_UUID=$(blkid -s UUID -o value "$P2_DEV" 2>/dev/null || true)
P1_PUUID=$(blkid -s PARTUUID -o value "$P1_DEV" 2>/dev/null || true)
P2_PUUID=$(blkid -s PARTUUID -o value "$P2_DEV" 2>/dev/null || true)
P3_DEV="/dev/${DISK}p3"
LUKS_UUID=$(blkid -s UUID -o value "$P3_DEV" 2>/dev/null || true)

[ -n "$P1_UUID" ] && ok "P1 UUID: $P1_UUID" || fail "P1 UUID missing"
[ -n "$P2_UUID" ] && ok "P2 UUID: $P2_UUID" || fail "P2 UUID missing"
[ -n "$P1_PUUID" ] && ok "P1 PARTUUID: $P1_PUUID" || fail "P1 PARTUUID missing"
[ -n "$P2_PUUID" ] && ok "P2 PARTUUID: $P2_PUUID" || fail "P2 PARTUUID missing"

# crypttab
CRYPTLINE=$(grep -E '^[[:space:]]*cryptroot[[:space:]]+' "$MNT/etc/crypttab" || true)
[ -n "$CRYPTLINE" ] || fail "crypttab lacks cryptroot line"
echo "$CRYPTLINE" | grep -q "UUID=$LUKS_UUID" && ok "crypttab UUID matches LUKS UUID" || echo "${YEL}[WARN] crypttab UUID != $LUKS_UUID$NC"

# cmdline
[ -s "$ESP/cmdline.txt" ] || fail "cmdline.txt missing on ESP"
CMD=$(cat "$ESP/cmdline.txt")
echo "$CMD" | grep -q 'root=/dev/mapper/rp5vg-root' && ok "cmdline root mapper is rp5vg-root" || fail "cmdline root mapper not set to rp5vg-root"
echo "$CMD" | grep -q "cryptdevice=UUID=$LUKS_UUID:cryptroot" && ok "cmdline cryptdevice UUID matches" || echo "${YEL}[WARN] cmdline cryptdevice UUID mismatch$NC"

# fstab: accept UUID= or PARTUUID=
FSTAB="$MNT/etc/fstab"
FSTAB=$(cat "$MNT/etc/fstab")
grep -Eq "((UUID=$P2_UUID)|(PARTUUID=$P2_PUUID)).*[[:space:]]/boot[[:space:]]" "$FSTAB" && ok "fstab has /boot (UUID or PARTUUID)" || fail "fstab lacks P2 for /boot"
grep -Eq "((UUID=$P1_UUID)|(PARTUUID=$P1_PUUID)).*[[:space:]]/boot/firmware[[:space:]]" "$FSTAB" && ok "fstab has /boot/firmware (UUID or PARTUUID)" || fail "fstab lacks P1 for /boot/firmware"

# ESP firmware presence
need_ok=true
for f in start4.elf fixup4.dat bcm2712-rpi-5-b.dtb; do
  [ -e "$ESP/$f" ] || { printf "%s[FAIL]%s Missing on ESP: %s\n" "$RED" "$NC" "$f"; need_ok=false; }
done
\$need_ok && ok "ESP has core firmware + DTB" || fail "ESP firmware incomplete"

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
  grep -q "UUID=${LUKS_UUID}" "${MNT}/root/RP5_RECOVERY.md" && ok "recovery doc references LUKS UUID" || warn "recovery doc UUID mismatch"
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


ok "POSTPROVISION_VALIDATE_OK"
exit 0
