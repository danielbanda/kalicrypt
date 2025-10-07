# RP5 Provisioning — Usage Guide

This is the canonical guide for provisioning NVMe with an encrypted root on Raspberry Pi (RP5 project).

## Entry points

**Preferred (package mode):**
```
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --plan
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --do-postcheck
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --yes
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --yes --do-postcheck
```

**Preferred (package mode) only.**
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --plan
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --do-postcheck
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --yes
python -m provision /dev/nvme0n1 --passphrase-file ~/secret.txt --yes --do-postcheck
```

## Flag semantics

- `--plan` and `--dry-run` are **strictly non-destructive** and print a JSON plan.
- `--do-postcheck` (by itself) is **non-destructive**: it opens the LUKS volume, mounts the target root, installs the post-boot checker, writes the recovery doc, unmounts and closes.
- `--yes` performs the full provision (partitioning, LUKS/LVM, rsync, firmware, boot plumbing, initramfs).

## Keyfile

- Use `--passphrase-file ~/secret.txt`. Tilde expands to `/home/<user>/secret.txt`. The program also expands `~` internally.
- The file must exist and be non-empty; permissions should be owner-only (e.g., `400` or `600`).

## Postcheck verification

```
L=$(blkid -s UUID -o value /dev/nvme0n1p3)
sudo cryptsetup open UUID=$L cryptroot --key-file ~/secret.txt --allow-discards
sudo vgchange -ay rp5vg
sudo mount /dev/mapper/rp5vg-root /mnt

test -x /mnt/usr/local/sbin/rp5-postboot-check && echo POSTCHECK_SCRIPT_OK || echo POSTCHECK_SCRIPT_MISSING
sudo test -s /mnt/root/RP5_RECOVERY.md && echo RECOVERY_DOC_OK || echo RECOVERY_DOC_MISSING

sudo umount /mnt
sudo vgchange -an rp5vg
sudo cryptsetup close cryptroot
```

## Troubleshooting quick hits

- If pre-boot hangs: ensure `config.txt` has an `initramfs <image> followkernel` line; ensure `cryptsetup-initramfs` and `lvm2` are installed in target; rebuild `update-initramfs -u`.
- If `luksFormat` fails: wipe signatures (`wipefs -a /dev/<p3>`), `blkdiscard` or zero first 16MiB, confirm keyfile path.

## Manual initramfs rebuild (NVMe root)

If you need to refresh the initramfs on a provisioned NVMe target, perform the following inside the installer host. The sequence
mirrors what the provisioner now automates.

1. **Mount the target and prep the chroot**

   ```bash
   sudo cryptsetup open /dev/nvme0n1p3 cryptroot
   sudo vgchange -ay rp5vg
   sudo mount /dev/mapper/rp5vg-root /mnt/nvme
   sudo mount /dev/nvme0n1p2 /mnt/nvme/boot
   sudo mount /dev/nvme0n1p1 /mnt/nvme/boot/firmware

   sudo mkdir -p /mnt/nvme/{dev,dev/pts,proc,sys,tmp}
   sudo mount --bind /dev     /mnt/nvme/dev
   sudo mount --bind /dev/pts /mnt/nvme/dev/pts
   sudo mount -t proc  proc   /mnt/nvme/proc
   sudo mount -t sysfs sys    /mnt/nvme/sys
   sudo chmod 1777 /mnt/nvme/tmp
   sudo cp /etc/resolv.conf /mnt/nvme/etc/resolv.conf
   ```

2. **Force `crypttab` to prompt in the initramfs**

   ```bash
   sudo sed -i -E 's|^(cryptroot[[:space:]]+UUID=[0-9a-f-]+)[[:space:]]+\S+|\1 none|' /mnt/nvme/etc/crypttab
   ```

3. **Rebuild the initramfs for the active kernel and publish it to the ESP**

   ```bash
   sudo chroot /mnt/nvme bash -lc '
   set -e
   kver=$(basename /lib/modules/* | head -n1)
   apt-get update || true
   dpkg -s cryptsetup-initramfs >/dev/null 2>&1 || apt-get install -y cryptsetup-initramfs
   dpkg -s lvm2                 >/dev/null 2>&1 || apt-get install -y lvm2
   dpkg -s initramfs-tools      >/dev/null 2>&1 || apt-get install -y initramfs-tools
   update-initramfs -c -k "$kver" || update-initramfs -u -k "$kver"
   cp -v "/boot/initrd.img-$kver" /boot/firmware/initramfs_2712
   lsinitramfs /boot/firmware/initramfs_2712 | egrep -i "cryptsetup|dm-crypt|lvm|nvme" | head
   '
   ```

4. **Quick triplet check**

   ```bash
   grep -n 'cryptdevice=UUID=.*:cryptroot' /mnt/nvme/boot/firmware/cmdline.txt
   grep -n '^cryptroot'                    /mnt/nvme/etc/crypttab
   grep -n '/dev/mapper/rp5vg-root'        /mnt/nvme/etc/fstab
   ls -lh /mnt/nvme/boot/firmware/initramfs_2712
   ```

5. **Cleanly unmount and close**

   ```bash
   sudo umount -R /mnt/nvme
   sudo vgchange -an rp5vg
   sudo cryptsetup close cryptroot
   ```


### Rsync policy
- Rsync is **strict by default**: any non-zero exit (including 23/24) aborts the run.
- Stats and itemized changes are printed in the final JSON to aid diagnosis.


## Canonical Module Invocation (package at project root)
```
sudo python -m provision /dev/nvme0n1 --esp-mb 256 --boot-mb 512 --passphrase-file ~/secret.txt --yes
```


### Output formatting
- Pretty JSON on stdout for terminal readability; JSONL logs remain one-line per event.
