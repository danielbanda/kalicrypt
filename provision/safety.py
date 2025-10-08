"""Guards and destructive-op refusals (skeleton)."""

from __future__ import annotations

import os


def guard_not_live_disk(device: str) -> tuple[bool, str]:
    """
    Refuse when target device appears to be the live ROOT/BOOT parent disk.
    Returns (ok, reason). Pure-Python guard that shells out via /proc to avoid deps.
    """
    import subprocess

    def _pdisk_of(mountpoint):
        try:
            src = subprocess.check_output(["findmnt", "-no", "SOURCE", mountpoint], text=True).strip()
            if not src:
                return ""
            # If src like /dev/nvme0n1p2 -> get parent name (PKNAME)
            try:
                pk = subprocess.check_output(["lsblk", "-no", "PKNAME", src], text=True).strip()
            except Exception:
                pk = ""
            return pk
        except Exception:
            return ""

    root_pd = _pdisk_of("/")
    boot_pd = _pdisk_of("/boot")
    try:
        # normalize like nvme0n1 (strip /dev/ and partitions)
        devname = subprocess.check_output(["lsblk", "-no", "PKNAME", device], text=True).strip()
    except Exception:
        devname = ""
    # Fallback: cut basename if PKNAME empty
    if not devname:
        devname = os.path.basename(device).rstrip("0123456789")
    # Compare
    for live in [root_pd, boot_pd]:
        if live and (live == devname or device.endswith(live) or live in device):
            return False, f"Target {device} looks like live disk ({live})."
    return True, ""
