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
- `--yes` performs the full provision (partitioning, LUKS/LVM, rsync, firmware, boot plumbing, initramfs). In full-run, `--skip-rsync` is disallowed.

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


### Rsync policy
- Rsync is **strict by default**: any non-zero exit (including 23/24) aborts the run.
- Stats and itemized changes are printed in the final JSON to aid diagnosis.


## Canonical Module Invocation (package at project root)
```
sudo python -m provision /dev/nvme0n1 --esp-mb 256 --boot-mb 512 --full-run --yes
```


### Output formatting
- Pretty JSON on stdout for terminal readability; JSONL logs remain one-line per event.
