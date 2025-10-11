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
OS_CHECK="${OS_CHECK:-0}"

echo "${BLU}[STEP] Inputs${NC} DEVICE=$DEVICE KEY_SRC=$KEY_SRC ESP_MB=$ESP_MB BOOT_MB=$BOOT_MB VG=$VG_NAME LV=$LV_NAME OS_CHECK=$OS_CHECK"

if [ "$(id -u)" != "0" ]; then echo "${RED}[FAIL] must run as root${NC}"; exit 1; fi
if [ ! -f "$KEY_SRC" ] || [ ! -s "$KEY_SRC" ]; then echo "${RED}[FAIL] missing or empty KEY_SRC:${NC} $KEY_SRC"; exit 1; fi
if [ ! -b "$DEVICE" ]; then echo "${RED}[FAIL] not a block device:${NC} $DEVICE"; exit 1; fi

echo "${BLU}[STEP] Kill holders and unmount if needed${NC}"
swapoff -a || true
sync || true
for d in "$MNT/tmp" "$MNT/var/tmp" "$MNT/proc" "$MNT/sys" "$MNT/dev" "$MNT/run" "$MNT/boot/firmware" "$MNT/boot" "$MNT"; do
  umount -l "$d" 2>/dev/null || true
done
dmsetup remove --retry "$LUKS_NAME" 2>/dev/null || true
vgchange -an "$VG_NAME" 2>/dev/null || true
cryptsetup close "$LUKS_NAME" 2>/dev/null || true

echo "${BLU}[STEP] Partition disk (GPT: p1=EFI $ESP_MB MiB, p2=boot $BOOT_MB MiB, p3=LUKS)${NC}"
sgdisk -Z "$DEVICE"
sgdisk -n 1:0:+"${ESP_MB}"M -t 1:ef00 "$DEVICE"
sgdisk -n 2:0:+"${BOOT_MB}"M -t 2:8300 "$DEVICE"
sgdisk -n 3:0:0            -t 3:8309 "$DEVICE"
blockdev --rereadpt "$DEVICE" || true
partprobe "$DEVICE" || true
partx -u "$DEVICE" || true
HD=$(command -v hdparm || true); [ -n "$HD" ] && hdparm -z "$DEVICE" || true

P1="${DEVICE}p1"; P2="${DEVICE}p2"; P3="${DEVICE}p3"

echo "${BLU}[STEP] Create LUKS2 + LVM${NC}"
echo "${YEL}[WARN] Proceeding will format $P3${NC}"
cryptsetup luksFormat "$P3" "$KEY_SRC" --type luks2 --pbkdf pbkdf2 --batch-mode
cryptsetup -q open "$P3" "$LUKS_NAME" --key-file "$KEY_SRC" --allow-discards
pvcreate -ff -y "/dev/mapper/$LUKS_NAME"
vgcreate "$VG_NAME" "/dev/mapper/$LUKS_NAME"
lvcreate -n "$LV_NAME" -l 100%FREE "$VG_NAME"

echo "${BLU}[STEP] Make filesystems${NC}"
mkfs.vfat -F 32 -n EFI "$P1"
wipefs -a "$P2" 2>/dev/null || true
mkfs.ext4 -F -L boot "$P2"
mkfs.ext4 -F -L root "/dev/mapper/${VG_NAME}-${LV_NAME}"

echo "${BLU}[STEP] Mount target${NC}"
mkdir -p "$MNT"
#mountpoint -q "$MNT/dev" || mount --bind /dev "$MNT/dev"
mount "/dev/mapper/${VG_NAME}-${LV_NAME}" "$MNT"
mkdir -p "$MNT/boot"
mount "$P2" "$MNT/boot"
mkdir -p "$MNT/boot/firmware"
mount -o umask=0077 "$P1" "$MNT/boot/firmware"
for d in dev proc sys run tmp var/tmp; do mkdir -p "$MNT/$d"; done
mount --bind /dev "$MNT/dev"
mount --bind /proc "$MNT/proc"
mount --bind /sys "$MNT/sys"
mount --bind /run "$MNT/run"
mount --bind /tmp "$MNT/tmp"
mount --bind /var/tmp "$MNT/var/tmp"
chmod 1777 "$MNT/tmp" "$MNT/var/tmp" || true

# ------------------------ ROOT RSYNC ------------------------
if [ "$SKIP_RSYNC" != "true" ]; then
  echo "${BLU}[STEP] Rsync root with excludes${NC}"
  rsync -aHAX --numeric-ids --delete-after --info=progress2 --stats \
    --exclude '/proc' --exclude '/sys' --exclude '/dev' --exclude '/run' \
    --exclude '/mnt' --exclude '/media' --exclude '/tmp' --exclude '/var/tmp' \
    --exclude '/etc/cryptsetup-keys.d/***' --exclude '/etc/cryptsetup-initramfs/conf-hook' \
    --exclude '/boot' --exclude '/boot/' --exclude '/boot/*' \
    --exclude '/boot/firmware' --exclude '/boot/firmware/*' \
    /  "$MNT/"
fi

KVER=$(uname -r)
rsync -aHAX "/lib/modules/$KVER"  "$MNT/lib/modules/"
rsync -aHAX /lib/firmware/        "$MNT/lib/firmware/"

echo "${BLU}[STEP] Write fstab, crypttab, cmdline (stable IDs)${NC}"
#cryptsetup luksDump "$P3" | grep -q "$LUKS_UUID" || echo "${YEL}[WARN] LUKS UUID mismatch${NC}"
# Resolve stable IDs once (after mkfs/cryptsetup)
P1_UUID=$(blkid -s UUID -o value "$P1");
P2_UUID=$(blkid -s UUID -o value "$P2");
LUKS_UUID=$(blkid -s UUID -o value "$P3")
ROOT_MAPPER="/dev/mapper/${VG_NAME}-${LV_NAME}"

#[ -b "$ROOT_MAPPER" ] || { echo "${RED}[FAIL] Missing root mapper device: $ROOT_MAPPER${NC}"; exit 1; }

# 1) fstab — use PARTUUID for /boot and /boot/firmware; mapper for /
#    vfat ESP with strict umask; ext4 defaults for / and /boot
tee "$MNT/etc/fstab" >/dev/null <<EOF
/dev/mapper/${VG_NAME}-${LV_NAME}  /               ext4  defaults,errors=remount-ro  0 1
UUID=$P2_UUID                      /boot           ext4  defaults                     0 2
UUID=$P1_UUID                      /boot/firmware  vfat  umask=0077                   0 2
EOF

install -d -m 0755 "$MNT/etc/cryptsetup-keys.d"
install -m 0600 "$KEY_SRC" "$MNT/etc/cryptsetup-keys.d/cryptroot.key"
install -d -m 0755 "$MNT/etc/cryptsetup-initramfs"
printf 'KEYFILE_PATTERN=/etc/cryptsetup-keys.d/*.key\nUMASK=0077\n' | tee "$MNT/etc/cryptsetup-initramfs/conf-hook" >/dev/null
chmod 0644 "$MNT/etc/cryptsetup-initramfs/conf-hook"
printf 'cryptroot  UUID=%s  /etc/cryptsetup-keys.d/cryptroot.key  luks,discard,initramfs\n' "$LUKS_UUID" | tee "$MNT/etc/crypttab" >/dev/null

# ------------------------ FIRMWARE TO ESP ------------------------
echo "${BLU}[STEP] Populate ESP with firmware (DTBs/overlays/elf)${NC}"
# Prefer in-target firmware if present, else host /boot/firmware
SRC_FW=""
if [ -d "$MNT/boot/firmware" ] && [ -f "$MNT/boot/firmware/start4.elf" ]; then
  SRC_FW="$MNT/boot/firmware/"
elif [ -d "/boot/firmware" ] && [ -f "/boot/firmware/start4.elf" ]; then
  SRC_FW="/boot/firmware/"
fi

# ------------------------ SYNC FIRMWARE FILES (-cmdline.txt) ------------------------
if [ -n "$SRC_FW" ]; then
  rsync -aH --delete --info=stats2 --exclude "cmdline.txt" "$SRC_FW" "$MNT/boot/firmware/"
else
  echo "${YEL}[WARN] No firmware source found; will rely on kernel package in chroot${NC}"
fi

CFG="$MNT/boot/firmware/config.txt"
touch "$CFG"
grep -qi '^\s*\[all\]\s*$' "$CFG" || printf '\n[all]\n' >>"$CFG"
grep -qi '^\s*initramfs\s\+\S\+\s\+followkernel\s*$' "$CFG" || printf 'initramfs %s followkernel\n' "$IMAGE_NAME" >>"$CFG"
# Bypass OS gate for non-RPiOS/older images
if ! grep -qi '^\s*os_check=' "$CFG"; then echo "os_check=$OS_CHECK" >> "$CFG"; else sed -i "s/^os_check=.*/os_check=$OS_CHECK/" "$CFG"; fi

# ------------------------ INITRAMFS BUILD ------------------------
echo "${BLU}[STEP] Rebuild initramfs inside chroot${NC}"
chroot "$MNT" /usr/sbin/update-initramfs -c -k "$KVER" || { echo "${YEL}[WARN] update-initramfs failed; continuing${NC}"; true; }
# copy the built image to ESP
if [ -f "$MNT/boot/initrd.img-$KVER" ]; then
  cp -f "$MNT/boot/initrd.img-$KVER" "$MNT/boot/firmware/$IMAGE_NAME"
fi

# ------------------------ ENSURE CMDLINE (post-firmware sync) ------------------------
echo "${BLU}[STEP] Ensure cmdline points to LUKS mapper (post-firmware sync)${NC}"
tee "$MNT/boot/firmware/cmdline.txt" >/dev/null <<EOF
cryptdevice=UUID=$LUKS_UUID:cryptroot root=$ROOT_MAPPER rootfstype=ext4 rootwait console=serial0,115200 console=tty1 fsck.repair=yes net.ifnames=0
EOF

# ------------------------ VERIFY FIRMWARE ------------------------
echo "${BLU}[STEP] Verify firmware on ESP${NC}"
REQ_OK=true
for f in start4.elf fixup4.dat overlays bcm2712-rpi-5-b.dtb "$IMAGE_NAME"; do
  if [ ! -e "$MNT/boot/firmware/$f" ]; then
    echo "${RED}[FAIL] Missing on ESP: $f${NC}"; REQ_OK=false
  fi
done
$REQ_OK || { echo "${RED}[RESULT] FAIL_ESP_FIRMWARE_INCOMPLETE${NC}"; exit 2; }

# ------------------------ CLEANUP ------------------------
echo "${BLU}[STEP] Cleanup mounts${NC}"
sync || true
for d in "$MNT/tmp" "$MNT/var/tmp" "$MNT/proc" "$MNT/sys" "$MNT/dev" "$MNT/run" "$MNT/boot/firmware" "$MNT/boot" "$MNT"; do
  umount -l "$d" 2>/dev/null || true
done
vgchange -an "$VG_NAME" 2>/dev/null || true
cryptsetup close "$LUKS_NAME" 2>/dev/null || true

echo "${GRN}[RESULT] ETE_DONE_OK${NC}"
exit 0
