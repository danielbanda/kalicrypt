from __future__ import annotations

# Recovery helpers (Phase 6)
import json
import os
import tarfile

from .executil import run


def write_recovery_doc(mnt: str, luks_uuid: str) -> dict:
    doc = (
        '# RP5 Recovery (NVMe LUKS Root)\n\n'
        '## Unlock\n'
        f'cryptsetup open UUID={luks_uuid} cryptroot --key-file ~/secret.txt --allow-discards\n\n'
        '## Activate LVM\n'
        'vgchange -ay rp5vg\n\n'
        '## Mount\n'
        'mount /dev/mapper/rp5vg-root /mnt\n'
        "mount $(blkid -o device -t TYPE=ext4 | grep -E 'nvme.*p2$') /mnt/boot\n"
        "mount $(blkid -o device -t TYPE=vfat | grep -E 'nvme.*p1$') /mnt/boot/firmware\n"
    )
    p = os.path.join(mnt, 'root', 'RP5_RECOVERY.md')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(doc)
    metadata = {
        'host_path': p,
        'target_path': '/root/RP5_RECOVERY.md',
        'exists': os.path.isfile(p),
    }
    return metadata


def install_postboot_check(mnt: str):
    script = (
        '#!/bin/sh\n'
        'set -e\n'
        'cryptsetup status cryptroot >/dev/null 2>&1 || { echo "cryptroot not active"; exit 1; }\n'
        'vgdisplay rp5vg >/dev/null 2>&1 || { echo "rp5vg missing"; exit 1; }\n'
        'exit 0\n'
    )
    dst = os.path.join(mnt, 'usr/local/sbin/rp5-postboot-check')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(script)
    run(['chmod', '0755', dst], check=False)


def bundle_artifacts(out_path: str, state: dict):
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    except Exception:
        pass
    with tarfile.open(out_path, 'w:gz') as tar:
        for p in ('/var/log/rp5/ete_nvme.jsonl', '/tmp/rp5-logs/ete_nvme.jsonl'):
            if os.path.isfile(p):
                tar.add(p, arcname=os.path.basename(p))
    with open(out_path + '.state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
