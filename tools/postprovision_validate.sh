#!/bin/sh
# RP5 post-provision validator (UUID-only, hardened)
set -eu
LC_ALL=C
export LC_ALL

RED=$(printf '\033[31m'); GRN=$(printf '\033[32m'); YEL=$(printf '\033[33m'); NC=$(printf '\033[0m')
ok()   { printf "%s[OK]%s %s\n"   "$GRN" "$NC" "$*"; }
warn() { printf "%s[WARN]%s %s\n" "$YEL" "$NC" "$*"; }
fail() { printf "%s[FAIL]%s %s\n" "$RED" "$NC" "$*"; exit 1; }

MNT="${1:-/mnt/nvme}"
ESP="$MNT/boot/firmware"

echo "whoami: $(whoami)"; id; echo "date: $(date -Is)"
echo "MNT=$MNT  ESP=$ESP"
echo "findmnt of MNT:"; findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS "$MNT" || true
echo "findmnt of ESP (if present):"; findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS "$ESP" || true

[ -e "$MNT/etc/crypttab" ] || fail "missing $MNT/etc/crypttab"
echo "ls -l of crypttab:"; ls -l "$MNT/etc/crypttab"
echo "stat -c '%U:%G %a %s %y' crypttab:"; stat -c '%U:%G %a %s %y' "$MNT/etc/crypttab"
echo "head -n 10 crypttab (showing special chars):"; sed -n '1,10p' "$MNT/etc/crypttab" | tr -c '[:print:]\n\t' '?'

ROOT_SRC="$(findmnt -no SOURCE "$MNT" 2>/dev/null || true)"
[ -n "${ROOT_SRC:-}" ] || ROOT_SRC="/dev/mapper/rp5vg-root"
DISK="$(lsblk -no pkname "$ROOT_SRC" 2>/dev/null || true)"
if [ -z "${DISK:-}" ]; then
  NVME_DEV="${NVME_DEV:-/dev/nvme0n1}"
  DISK="$(basename "$NVME_DEV")"
fi

: "${P1:="/dev/${DISK}p1"}"
: "${P2:="/dev/${DISK}p2"}"
: "${P3:="/dev/${DISK}p3"}"

P1_UUID="$(blkid -s UUID -o value "$P1" 2>/dev/null || true)"
P2_UUID="$(blkid -s UUID -o value "$P2" 2>/dev/null || true)"
P1_PUUID="$(blkid -s PARTUUID -o value "$P1" 2>/dev/null || true)"
P2_PUUID="$(blkid -s PARTUUID -o value "$P2" 2>/dev/null || true)"
LUKS_UUID="$(blkid -s UUID -o value "$P3" 2>/dev/null || true)"

[ -n "$P1_UUID" ] && ok "P1 UUID: $P1_UUID" || fail "P1 UUID missing"
[ -n "$P2_UUID" ] && ok "P2 UUID: $P2_UUID" || fail "P2 UUID missing"
[ -n "$P1_PUUID" ] && ok "P1 PARTUUID: $P1_PUUID" || warn "P1 PARTUUID missing"
[ -n "$P2_PUUID" ] && ok "P2 PARTUUID: $P2_PUUID" || warn "P2 PARTUUID missing"

CRYPTLINE="$(grep -E '^[[:space:]]*cryptroot[[:space:]]+' "$MNT/etc/crypttab" || true)"
[ -n "$CRYPTLINE" ] || fail "crypttab lacks cryptroot line"
echo "$CRYPTLINE" | grep -q "UUID=$LUKS_UUID" && ok "crypttab UUID matches LUKS UUID" || warn "crypttab UUID != $LUKS_UUID"

[ -s "$ESP/cmdline.txt" ] || fail "cmdline.txt missing on ESP"
CMD="$(cat "$ESP/cmdline.txt")"
printf '%s
' "$CMD" | grep -q 'root=/dev/mapper/rp5vg-root' && ok "cmdline root mapper is rp5vg-root" || fail "cmdline root mapper not set to rp5vg-root"
printf '%s
' "$CMD" | grep -q "cryptdevice=UUID=$LUKS_UUID" && ok "cmdline cryptdevice UUID matches" || warn "cmdline cryptdevice UUID mismatch"

FSTAB="$MNT/etc/fstab"
[ -s "$FSTAB" ] || fail "fstab missing"

boot_ok="$(awk -v u="$P2_UUID" ' $0 !~ /^[[:space:]]*#/ && NF>=2 { if ($2=="/boot" && $1=="UUID=" u) { print "yes"; exit } }' "$FSTAB" || true)"
firm_ok="$(awk -v u="$P1_UUID" ' $0 !~ /^[[:space:]]*#/ && NF>=2 { if ($2=="/boot/firmware" && $1=="UUID=" u) { print "yes"; exit } }' "$FSTAB" || true)"

[ "${boot_ok:-}" = "yes" ] && ok "fstab has /boot (UUID only)" || fail "fstab lacks UUID for /boot"
[ "${firm_ok:-}"  = "yes" ] && ok "fstab has /boot/firmware (UUID only)" || fail "fstab lacks UUID for /boot/firmware"

missing=0
for f in start4.elf fixup4.dat bcm2712-rpi-5-b.dtb; do
  printf "Checking for %s on ESP '%s/%s'\n" "$f" "$ESP" "$f"
  if [ ! -e "$ESP/$f" ]; then
    printf "%s[FAIL]%s Missing on ESP: %s\n" "$RED" "$NC" "$f"
    missing=$((missing+1))
  fi
done
if [ "$missing" -eq 0 ]; then ok "ESP has core firmware + DTB"; else fail "ESP firmware incomplete"; fi

cfg="$ESP/config.txt"
[ -s "$cfg" ] || fail "config.txt missing"
img="$(awk '/^[[:space:]]*initramfs[[:space:]]+[[:graph:]]+[[:space:]]+followkernel([[:space:]]|$)/ {im=$2} END{if(im!="") print im}' "$cfg")"
[ -n "$img" ] || fail "config.txt missing initramfs line (expected: initramfs <image> followkernel)"
[ -s "$ESP/$img" ] || fail "initramfs image missing: $ESP/$img"

if command -v lsinitramfs >/dev/null 2>&1; then
  out="$(lsinitramfs "$ESP/$img" || true)"
  printf '%s
' "$out" | grep -Eq '(^|/)cryptsetup(\.static)?$' && ok "initramfs contains cryptsetup" || fail "initramfs missing cryptsetup"
  printf '%s
' "$out" | grep -Eq '(^|/)lvm(\.static)?$'        && ok "initramfs contains lvm"        || fail "initramfs missing lvm"
else
  warn "lsinitramfs not found; skipping image contents check"
fi

if [ -x "$MNT/usr/local/sbin/rp5-postboot-check" ]; then ok "postboot-check installed"; else warn "postboot-check not found"; fi
if [ -s "$MNT/root/RP5_RECOVERY.md" ]; then
  if grep -q "UUID=${LUKS_UUID}" "$MNT/root/RP5_RECOVERY.md"; then ok "recovery doc references LUKS UUID"; else warn "recovery doc UUID mismatch"; fi
else
  warn "recovery doc not found"
fi

if command -v cryptsetup >/dev/null 2>&1; then
  if cryptsetup luksDump "$P3" 2>/dev/null | grep -q 'label:[[:space:]]*rp5root'; then
    ok "LUKS label is rp5root"
  else
    warn "LUKS label not 'rp5root' (non-blocking)"
  fi
fi

ok "POSTPROVISION_VALIDATE_OK"
exit 0
