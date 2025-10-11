#!/bin/sh
set -eu
LC_ALL=C
export LC_ALL
RED=$(printf '\033[31m'); GRN=$(printf '\033[32m'); YEL=$(printf '\033[33m'); BLU=$(printf '\033[34m'); NC=$(printf '\033[0m')
ok(){ printf "%s[OK]%s %s\n" "$GRN" "$NC" "$*"; }
warn(){ printf "%s[WARN]%s %s\n" "$YEL" "$NC" "$*"; }
fail(){ printf "%s[FAIL]%s %s\n" "$RED" "$NC" "$*"; exit 1; }

MNT="${MNT:-/mnt/nvme}"
ESP="${ESP:-$MNT/boot/firmware}"
LUKS_DEV="${LUKS_DEV:-/dev/nvme0n1p3}"
LUKS_NAME="${LUKS_NAME:-cryptroot}"
VG_NAME="${VG_NAME:-rp5vg}"
LV_NAME="${LV_NAME:-root}"
TPM_PCRS="${TPM_PCRS:-7}"
IMAGE_NAME="${IMAGE_NAME:-initramfs_2712}"

[ "$(id -u)" = "0" ] || fail "run as root"
[ -d "$MNT" ] || fail "MNT not found: $MNT"
[ -d "$ESP" ] || fail "ESP not found: $ESP"
[ -b "$LUKS_DEV" ] || fail "LUKS device not found: $LUKS_DEV"
[ -e /dev/tpm0 ] || fail "/dev/tpm0 missing (enable tpm-slb9670 overlay, reboot)"

ok "Environment looks sane"
tpm2_selftest >/dev/null 2>&1 && ok "TPM self-test OK" || fail "TPM self-test failed"
tpm2_getrandom 8 >/dev/null 2>&1 && ok "TPM random OK" || warn "tpm2_getrandom failed (non-blocking)"

LUKS_UUID="$(blkid -s UUID -o value "$LUKS_DEV" 2>/dev/null || true)"
[ -n "$LUKS_UUID" ] || fail "could not read LUKS UUID from $LUKS_DEV"

[ -e "$MNT/etc/crypttab" ] || touch "$MNT/etc/crypttab"
[ -e "$MNT/etc/cryptsetup-initramfs" ] || mkdir -p "$MNT/etc/cryptsetup-initramfs"

need_pkgs="tpm2-tools clevis clevis-luks"
binds(){
  mount --bind /dev "$MNT/dev"
  mount --bind /proc "$MNT/proc"
  mount --bind /sys "$MNT/sys"
  mount --bind /run "$MNT/run"
}
unbinds(){
  umount -l "$MNT/run" 2>/dev/null || true
  umount -l "$MNT/sys" 2>/dev/null || true
  umount -l "$MNT/proc" 2>/dev/null || true
  umount -l "$MNT/dev" 2>/dev/null || true
}
pkg_missing=false
for p in $need_pkgs; do
  chroot "$MNT" dpkg -s "$p" >/dev/null 2>&1 || { pkg_missing=true; break; }
done
if $pkg_missing; then
  ok "Installing TPM/Clevis packages in target"
  binds
  chroot "$MNT" apt-get update -y
  chroot "$MNT" apt-get install -y $need_pkgs
  unbinds
else
  ok "Required packages already present in target"
fi

already_bound=false
if clevis luks list -d "$LUKS_DEV" >/dev/null 2>&1; then
  if clevis luks list -d "$LUKS_DEV" 2>/dev/null | grep -q '"tpm2"'; then
    already_bound=true
    ok "Clevis TPM2 binding already present on $LUKS_DEV"
  fi
fi

if ! $already_bound; then
  ok "Binding Clevis TPM2 to $LUKS_DEV (PCRs=${TPM_PCRS})"
  clevis luks bind -d "$LUKS_DEV" tpm2 "{"pcr_ids":"$TPM_PCRS"}" || fail "Clevis bind failed"
  ok "Clevis binding created"
fi

sed -i -e "/^[[:space:]]*cryptroot[[:space:]]/d" "$MNT/etc/crypttab"
printf "cryptroot  UUID=%s  none  luks,discard,initramfs,keyscript=/lib/cryptsetup/scripts/decrypt-clevis\n" "$LUKS_UUID" >> "$MNT/etc/crypttab"
ok "crypttab updated for clevis keyscript"
printf 'UMASK=0077\n' > "$MNT/etc/cryptsetup-initramfs/conf-hook"

KVER="$(chroot "$MNT" uname -r)"
ok "Target kernel: $KVER"
binds
chroot "$MNT" update-initramfs -u -k "$KVER" || fail "update-initramfs failed in target"
unbinds

if [ -f "$MNT/boot/initrd.img-$KVER" ]; then
  cp -f "$MNT/boot/initrd.img-$KVER" "$ESP/$IMAGE_NAME"
  ok "ESP updated: $ESP/$IMAGE_NAME"
else
  fail "initramfs not found at $MNT/boot/initrd.img-$KVER"
fi

CFG="$ESP/config.txt"; touch "$CFG"
grep -qi '^\s*\[all\]\s*$' "$CFG" || printf '\n[all]\n' >>"$CFG"
if grep -qi '^[[:space:]]*initramfs[[:space:]]\+\S\+[[:space:]]\+followkernel' "$CFG"; then
  sed -i "s#^[[:space:]]*initramfs[[:space:]]\+\S\+[[:space:]]\+followkernel#initramfs $IMAGE_NAME followkernel#g" "$CFG"
else
  printf "initramfs %s followkernel\n" "$IMAGE_NAME" >>"$CFG"
fi
grep -qi '^\s*os_check=' "$CFG" || echo "os_check=0" >> "$CFG"
ok "config.txt ensures initramfs + os_check=0"

if command -v lsinitramfs >/dev/null 2>&1; then
  out="$(lsinitramfs "$ESP/$IMAGE_NAME" || true)"
  printf '%s
' "$out" | grep -Eq '(^|/)cryptsetup(\.static)?$' && ok "initramfs contains cryptsetup" || fail "initramfs missing cryptsetup"
  printf '%s
' "$out" | grep -Eq '(^|/)lvm(\.static)?$'        && ok "initramfs contains lvm"        || fail "initramfs missing lvm"
  printf '%s
' "$out" | grep -Eq '(^|/)(decrypt-clevis|clevis-luks-unlock)(\.sh)?$' && ok "initramfs contains clevis unlock" || fail "initramfs missing clevis unlock script"
else
  warn "lsinitramfs not available on host; skipping image content checks"
fi

ok "TPM2 auto-unlock configured (Clevis). Passphrase slot retained for fallback."
echo "${GRN}[RESULT] TPM_ENROLL_OK${NC}"