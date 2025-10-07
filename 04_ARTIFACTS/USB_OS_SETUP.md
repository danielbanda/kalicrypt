# USB OS Setup (Builder USB)

sudo apt-get update && apt-get -y full-upgrade
sudo apt-get install -y cryptsetup-initramfs lvm2 rsync parted dosfstools jq python3 gh git

lsblk -o NAME,TYPE,SIZE,RO,DISC-ALN,DISC-GRAN,DISC-MAX,DISC-ZERO,MOUNTPOINT
sudo python -m provision /dev/nvme0n1 --esp-mb 256 --boot-mb 512 --passphrase-file ~/secret.txt --yes
