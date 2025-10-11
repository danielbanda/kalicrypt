#!/bin/sh
set -eu

GRN=$(printf '\033[32m'); YEL=$(printf '\033[33m'); RED=$(printf '\033[31m'); BLU=$(printf '\033[34m'); NC=$(printf '\033[0m')

DEVICE="${DEVICE:-/dev/nvme0n1}"
KEY_SRC="${KEY_SRC:-$HOME/secret.txt}"
VG_NAME="${VG_NAME:-rp5vg}"
LV_NAME="${LV_NAME:-root}"
ESP_MB="${ESP_MB:-256}"
BOOT_MB="${BOOT_MB:-512}"
MNT="${MNT:-/mnt/nvme}"
LUKS_NAME="${LUKS_NAME:-cryptroot}"
IMAGE_NAME="${IMAGE_NAME:-initramfs_2712}"
SKIP_RSYNC="${SKIP_RSYNC:-false}"

echo "$BLU[STEP] Inputs$NC DEVICE=$DEVICE KEY_SRC=$KEY_SRC ESP_MB=$ESP_MB BOOT_MB=$BOOT_MB VG=$VG_NAME LV=$LV_NAME"

if [ "$(id -u)" != "0" ]; then echo "$RED[FAIL] must run as root$NC"; exit 1; fi
if [ ! -f "$KEY_SRC" ] || [ ! -s "$KEY_SRC" ]; then echo "$RED[FAIL] missing or empty KEY_SRC:$NC $KEY_SRC"; exit 1; fi
if [ ! -b "$DEVICE" ]; then echo "$RED[FAIL] not a block device:$NC $DEVICE"; exit 1; fi

echo "$BLU[STEP] Kill holders and unmount if needed$NC"
swapoff -a || true
sync || true
umount -l "$MNT/tmp" 2>/dev/null || true
umount -l "$MNT/var/tmp" 2>/dev/null || true
umount -l "$MNT/proc" 2>/dev/null || true
umount -l "$MNT/sys" 2>/dev/null || true
umount -l "$MNT/dev" 2>/dev/null || true
umount -l "$MNT/run" 2>/dev/null || true
umount -l "$MNT/boot/firmware" 2>/dev/null || true
umount -l "$MNT/boot" 2>/dev/null || true
umount -l "$MNT" 2>/dev/null || true
dmsetup remove --retry "$LUKS_NAME" 2>/dev/null || true
vgchange -an "$VG_NAME" 2>/dev/null || true
cryptsetup close "$LUKS_NAME" 2>/dev/null || true

echo "$BLU[STEP] Partition disk (GPT: p1=EFI $ESP_MB MiB, p2=boot $BOOT_MB MiB, p3=LUKS)$NC"
sgdisk -Z "$DEVICE"
sgdisk -n 1:0:+"${ESP_MB}"M -t 1:ef00 "$DEVICE"
sgdisk -n 2:0:+"${BOOT_MB}"M -t 2:8300 "$DEVICE"
sgdisk -n 3:0:0            -t 3:8309 "$DEVICE"
blockdev --rereadpt "$DEVICE" || true
partprobe "$DEVICE" || true
partx -u "$DEVICE" || true
HD=$(command -v hdparm || true); [ -n "$HD" ] && hdparm -z "$DEVICE" || true

P1="${DEVICE}p1"; P2="${DEVICE}p2"; P3="${DEVICE}p3"

if [ "$SKIP_RSYNC" != true ]; then
  echo "$BLU[STEP] Create LUKS2 + LVM$NC"
  echo "$YEL[WARN] Proceeding will format $P3$NC"
  cryptsetup luksFormat "$P3" "$KEY_SRC" --type luks2 --pbkdf pbkdf2 --batch-mode
  cryptsetup -q open "$P3" "$LUKS_NAME" --key-file "$KEY_SRC" --allow-discards
  pvcreate -ff -y "/dev/mapper/$LUKS_NAME"
  vgcreate "$VG_NAME" "/dev/mapper/$LUKS_NAME"
  lvcreate -n "$LV_NAME" -l 100%FREE "$VG_NAME"

  echo "$BLU[STEP] Make filesystems$NC"
  mkfs.vfat -F 32 -n EFI "$P1"
  wipefs -a "$P2" 2>/dev/null || true
  mkfs.ext4 -F -L boot "$P2"
  mkfs.ext4 -F -L root "/dev/mapper/${VG_NAME}-${LV_NAME}"
else
  echo "$BLU[STEP] Remount LUKS2 + LVM$NC"
  sudo cryptsetup open /dev/nvme0n1p3 cryptroot --key-file ~/secret.txt
  sudo vgscan --mknodes && sudo vgchange -ay rp5vg
  sudo install -d /mnt/nvme /mnt/nvme/boot /mnt/nvme/boot/firmware
  sudo mount -o ro /dev/mapper/rp5vg-root /mnt/nvme
  sudo mount -o ro /dev/nvme0n1p2 /mnt/nvme/boot
  sudo mount -o ro /dev/nvme0n1p1 /mnt/nvme/boot/firmware
  sudo udevadm settle
fi

echo "$BLU[STEP] Mount target$NC"
mkdir -p "$MNT"
mount "/dev/mapper/${VG_NAME}-${LV_NAME}" "$MNT"
mkdir -p "$MNT/boot"
mount "$P2" "$MNT/boot"
mkdir -p "$MNT/boot/firmware"
mount -o umask=0077 "$P1" "$MNT/boot/firmware"
mkdir -p "$MNT/dev" "$MNT/proc" "$MNT/sys" "$MNT/run" "$MNT/tmp" "$MNT/var/tmp"
mount --bind /dev "$MNT/dev"
mount --bind /proc "$MNT/proc"
mount --bind /sys "$MNT/sys"
mount --bind /run "$MNT/run"
mount --bind /tmp "$MNT/tmp"
mount --bind /var/tmp "$MNT/var/tmp"
chmod 1777 "$MNT/tmp" "$MNT/var/tmp" || true

echo "$BLU[STEP] Seed firmware partition from host /boot/firmware$NC"
if [ "$SKIP_RSYNC" != true ]; then
  echo "$BLU[STEP] Rsync root with excludes$NC"
  rsync -aHAX --numeric-ids --delete-after --info=progress2 --stats \
    --exclude '/proc' --exclude '/sys' --exclude '/dev' --exclude '/run' \
    --exclude '/mnt' --exclude '/media' --exclude '/tmp' --exclude '/var/tmp' \
    --exclude '/etc/cryptsetup-keys.d/***' --exclude '/etc/cryptsetup-initramfs/conf-hook' \
    --exclude '/boot' --exclude '/boot/' --exclude '/boot/*' \
    --exclude '/boot/firmware' --exclude '/boot/firmware/*' \
    /  "$MNT/"
fi

KVER=$(uname -r)
sudo rsync -aHAX "/lib/modules/$KVER"  /mnt/nvme/lib/modules/
sudo rsync -aHAX /lib/firmware/        /mnt/nvme/lib/firmware/

#echo "$BLU[STEP] Write fstab, crypttab, cmdline$NC"
#ROOT_UUID=$(blkid -s UUID -o value "/dev/mapper/${VG_NAME}-${LV_NAME}" || true)
#printf '/dev/mapper/%s-%s / ext4 defaults,errors=remount-ro 0 1\n' "$VG_NAME" "$LV_NAME" | tee "$MNT/etc/fstab" >/dev/null
#printf '%s /boot ext4 defaults 0 2\n' "$P2" | tee -a "$MNT/etc/fstab" >/dev/null
#printf '%s /boot/firmware vfat defaults 0 2\n' "$P1" | tee -a "$MNT/etc/fstab" >/dev/null
#printf 'cryptdevice=UUID=%s:%s root=/dev/mapper/%s-%s rootfstype=ext4 rootwait\n' "$(blkid -s UUID -o value "$P3")" "$LUKS_NAME" "$VG_NAME" "$LV_NAME" | tee "$MNT/boot/firmware/cmdline.txt" >/dev/null
echo "$BLU[STEP] Write fstab, crypttab, cmdline (stable IDs)$NC"

# Resolve stable IDs once (after mkfs/cryptsetup)
P1_PARTUUID=$(blkid -s PARTUUID -o value "$P1")
P2_PARTUUID=$(blkid -s PARTUUID -o value "$P2")
LUKS_UUID=$(blkid -s UUID -o value "$P3")            # LUKS container UUID (not PARTUUID)
ROOT_MAPPER="/dev/mapper/${VG_NAME}-${LV_NAME}"

# 1) fstab — use PARTUUID for /boot and /boot/firmware; mapper for /
#    vfat ESP with strict umask; ext4 defaults for / and /boot
tee "$MNT/etc/fstab" >/dev/null <<EOF
/dev/mapper/${VG_NAME}-${LV_NAME}  /               ext4  defaults,errors=remount-ro  0 1
PARTUUID=$P2_PARTUUID              /boot           ext4  defaults                     0 2
PARTUUID=$P1_PARTUUID              /boot/firmware  vfat  umask=0077                   0 2
EOF

# 2) crypttab — point at the LUKS UUID and staged key; include ,initramfs
sudo tee "$MNT/etc/crypttab" >/dev/null <<EOF
cryptroot  UUID=$LUKS_UUID  /etc/cryptsetup-keys.d/cryptroot.key  luks,discard,initramfs
EOF
sudo chmod 0644 "$MNT/etc/crypttab"

# 3) cmdline.txt — must match the same LUKS UUID + mapper root
sudo tee "$MNT/boot/firmware/cmdline.txt" >/dev/null <<EOF
cryptdevice=UUID=$LUKS_UUID:cryptroot root=$ROOT_MAPPER rootfstype=ext4 rootwait
EOF



echo "$BLU[STEP] Stage keyfile, hook, crypttab$NC"
install -d -m 0755 "$MNT/etc/cryptsetup-keys.d"
install -m 0600 "$KEY_SRC" "$MNT/etc/cryptsetup-keys.d/cryptroot.key"
install -d -m 0755 "$MNT/etc/cryptsetup-initramfs"
printf 'KEYFILE_PATTERN=/etc/cryptsetup-keys.d/*.key\nUMASK=0077\n' | tee "$MNT/etc/cryptsetup-initramfs/conf-hook" >/dev/null
chmod 0644 "$MNT/etc/cryptsetup-initramfs/conf-hook"
UUID_LUKS=$(blkid -s UUID -o value "$P3")
printf 'cryptroot  UUID=%s  /etc/cryptsetup-keys.d/cryptroot.key  luks,discard,initramfs\n' "$UUID_LUKS" | tee "$MNT/etc/crypttab" >/dev/null
echo "$UUID_LUKS"

echo "$BLU[STEP] Ensure firmware references initramfs image$NC"
CFG="$MNT/boot/firmware/config.txt"
touch "$CFG"
grep -qi '^\s*\[all\]\s*$' "$CFG" || printf '\n[all]\n' >>"$CFG"
grep -qi '^\s*initramfs\s\+\S\+\s\+followkernel\s*$' "$CFG" || printf 'initramfs %s followkernel\n' "$IMAGE_NAME" >>"$CFG"

echo "$BLU[STEP] Add staged key to a LUKS slot$NC"
cryptsetup luksAddKey "$P3" "$MNT/etc/cryptsetup-keys.d/cryptroot.key" --key-file "$KEY_SRC"

echo "$BLU[STEP] Rebuild initramfs inside chroot (no apt)$NC"
sudo chroot /mnt/nvme /usr/sbin/update-initramfs -c -k "$KVER"

# copy that single file to firmware (no wildcard)
sudo chroot /mnt/nvme /bin/cp -f "/boot/initrd.img-$KVER" "/boot/firmware/initramfs_2712"

echo "$BLU[STEP] Verify key is embedded in image$NC"
if lsinitramfs /mnt/nvme/boot/firmware/initramfs_2712 | egrep -q '^(crypto_keyfile\.bin|etc/cryptsetup-keys\.d/cryptroot\.key|cryptroot/.+key)$'; then
  echo "$GRN[OK] keyfile found inside $IMAGE_NAME$NC"
else
  echo "$RED[FAIL] keyfile missing inside $IMAGE_NAME$NC"
  RESULT="FAIL_INITRAMFS_VERIFY"; RC=1
fi

echo "$BLU[STEP] Cleanup mounts$NC"
sync || true
umount -l "$MNT/tmp" 2>/dev/null || true
umount -l "$MNT/var/tmp" 2>/dev/null || true
umount -l "$MNT/proc" 2>/dev/null || true
umount -l "$MNT/sys" 2>/dev/null || true
umount -l "$MNT/dev" 2>/dev/null || true
umount -l "$MNT/run" 2>/dev/null || true
umount -l "$MNT/boot/firmware" 2>/dev/null || true
umount -l "$MNT/boot" 2>/dev/null || true
umount -l "$MNT" 2>/dev/null || true
vgchange -an "$VG_NAME" 2>/dev/null || true
cryptsetup close "$LUKS_NAME" 2>/dev/null || true

if [ "${RESULT:-}" = "FAIL_INITRAMFS_VERIFY" ]; then
  echo "$RED[RESULT]: FAIL_INITRAMFS_VERIFY$NC"; exit "${RC:-1}"
fi

echo "$GRN[RESULT] ETE_DONE_OK$NC"
exit 0