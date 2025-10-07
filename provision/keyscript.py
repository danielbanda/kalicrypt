
"""Optional TPM keyscript installer (Phase 3).
This is a minimal, pluggable hook; it does NOT guarantee TPM unlock—it's a stub you can replace.
"""
import os, stat
from .executil import run

SCRIPT_PATH = "/lib/cryptsetup/scripts/cryptroot-tpm"

SCRIPT_CONTENT = """#!/bin/sh
# Minimal placeholder keyscript. Always exit non-zero to fall back to passphrase.
# Replace with clevis/tpm2 integration as needed.
exit 1
"""

def install_tpm_keyscript(mnt: str, dry_run: bool=False) -> str:
    dst = os.path.join(mnt, SCRIPT_PATH.lstrip('/'))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(SCRIPT_CONTENT)
    os.chmod(dst, stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR|stat.S_IRGRP|stat.S_IXGRP|stat.S_IROTH|stat.S_IXOTH)
    # Optionally ensure tools are present; best-effort only
    run(["chroot", mnt, "/usr/bin/apt-get", "-y", "update"], check=False, dry_run=dry_run)
    run(["chroot", mnt, "/usr/bin/apt-get", "-y", "install", "tpm2-tools", "clevis", "clevis-initramfs"], check=False, dry_run=dry_run)
    return SCRIPT_PATH
