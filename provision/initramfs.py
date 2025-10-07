
"""Ensure/rebuild/verify initramfs in target root (Phase 2)."""
import os, re, subprocess
from .executil import run

def ensure_packages(mnt: str, dry_run: bool=False):
    ch = ["chroot", mnt, "/usr/bin/apt-get", "-y", "update"]
    run(ch, check=False, dry_run=dry_run)
    run(["chroot", mnt, "/usr/bin/apt-get", "-y", "install", "cryptsetup-initramfs", "lvm2"], check=False, dry_run=dry_run)

def rebuild(mnt: str, dry_run: bool=False):
    run(["chroot", mnt, "/usr/sbin/update-initramfs", "-u"], check=False, dry_run=dry_run)

def verify(dst_boot_fw: str) -> str:
    cfg = os.path.join(dst_boot_fw, 'config.txt')
    if not os.path.exists(cfg):
        # write a safe default that references the newest initrd
        ir = newest_initrd(dst_boot_fw)
        with open(cfg,'w',encoding='utf-8') as f: f.write(f"initramfs {os.path.basename(ir)} followkernel\n")
    with open(cfg,'r',encoding='utf-8') as f:
        m = re.search(r'^initramfs\s+([^\s#]+)', f.read(), re.M)
    if not m:
        raise RuntimeError("initramfs: config.txt missing initramfs line")
    ir = os.path.join(dst_boot_fw, m.group(1))
    if not os.path.isfile(ir) or os.path.getsize(ir) < 131072:
        raise RuntimeError("initramfs: image missing or too small")
    # ensure cryptsetup+lvm present
    out = subprocess.check_output(["lsinitramfs", ir], text=True)
    if "cryptsetup" not in out or "lvm" not in out:
        raise RuntimeError("initramfs: missing cryptsetup or lvm in image")
    return ir

def newest_initrd(dst_boot_fw: str) -> str:
    cands = sorted([p for p in os.listdir(dst_boot_fw) if p.startswith('initramfs')], reverse=True)
    if not cands:
        raise RuntimeError("initramfs: no initramfs* found in /boot/firmware")
    return os.path.join(dst_boot_fw, cands[0])
