# USB OS Setup (Builder USB)

apt-get update && apt-get -y full-upgrade
apt-get install -y cryptsetup-initramfs lvm2 rsync parted dosfstools jq python3

lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS
python3 provision/go.py initramfs --distro auto --rebuild-all || true
provision/nvme_esp_fix.sh /dev/nvme0n1 /boot/firmware
provision/ete_run.sh
