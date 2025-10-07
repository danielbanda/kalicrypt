# NVMe dry-run review — 2025-10-07

## Key observations from plan output
- Target `/dev/nvme0n1` currently reports no partitions; `lsblk` only lists the bare disk. That matches a blank target and means the provisioner must create `p1`–`p3` during the full run.
- The detected root source is `/dev/sda2`, so rsync will lift the live root from that partition.
- The dry-run was invoked without `--passphrase-file`, so the stored plan has `passphrase_file: null`. The full run must supply a readable key file.

## Preflight checklist before running with `--yes`
- Confirm the key file exists for the sudo context: `sudo test -s /root/secret.txt`. Using `~/secret.txt` with `sudo` resolves to `/root/secret.txt`; copy it there or pass an absolute path if the file lives elsewhere. The CLI refuses missing or empty files before formatting LUKS.【F:provision/cli.py†L417-L433】
- Check nothing is holding the NVMe device: `sudo fuser -vm /dev/nvme0n1`. Kill any remaining holders so `parted` and `wipefs` can proceed without interference. The flow will also call `kill_holders`, but clearing blockers now avoids repeated prompts.【F:provision/cli.py†L126-L148】
- Verify the active root really is `/dev/sda2`: `findmnt /`. If it differs, adjust expectations or rerun `--plan` from the booted system you want copied.
- Back up the dry-run JSON artifact from `/home/admin/rp5/03_LOGS/` after generating a new plan with the real key file so the stored metadata reflects the file path you will use.

## Recommended execution order
1. `sudo python -m provision /dev/nvme0n1 --plan --esp-mb 256 --boot-mb 512 --passphrase-file /root/secret.txt`
2. Review the refreshed plan and logs for the correct key-file path and rsync source.
3. `sudo python -m provision /dev/nvme0n1 --yes --esp-mb 256 --boot-mb 512 --passphrase-file /root/secret.txt`
4. Optionally follow with `--do-postcheck` once the full run finishes.
