
"""Write fstab/crypttab/cmdline and validate (Phase 2)."""
import os, re, json, subprocess
from .executil import run

def write_fstab(mnt: str, p1_uuid: str, p2_uuid: str):
    fstab = os.path.join(mnt, 'etc/fstab')
    os.makedirs(os.path.dirname(fstab), exist_ok=True)
    data = f"""UUID={p1_uuid}  /boot/firmware  vfat   defaults,uid=0,gid=0,umask=0077  0  1
UUID={p2_uuid}  /boot           ext4   defaults                           0  2
/dev/mapper/rp5vg-root  /       ext4   defaults                           0  1
"""
    with open(fstab,'w',encoding='utf-8') as f: f.write(data)

def write_crypttab(mnt: str, luks_uuid: str, passfile: str|None, keyscript_path: str|None=None):
    ct = os.path.join(mnt, 'etc/crypttab')
    os.makedirs(os.path.dirname(ct), exist_ok=True)
    key = passfile if passfile else 'none'
    opts = 'luks,discard'
    if keyscript_path:
        opts += f',keyscript={keyscript_path}'
    line = f"cryptroot  UUID={luks_uuid}  {key}  {opts}\n"
    with open(ct, 'w', encoding='utf-8') as f:
        f.write(line)
        try:
            f.flush(); os.fsync(f.fileno())
        except Exception:
            pass

def write_cmdline(dst_boot_fw: str, luks_uuid: str):
    p = os.path.join(dst_boot_fw,'cmdline.txt')
    cmd = f"console=serial0,115200 console=tty1 root=/dev/mapper/rp5vg-root rootfstype=ext4 fsck.repair=yes rootwait cryptdevice=UUID={luks_uuid}:cryptroot"
    if os.path.exists(p):
        txt = open(p,'r',encoding='utf-8').read()
        if 'cryptdevice=' in txt and 'root=/dev/mapper/rp5vg-root' in txt:
            return
    with open(p,'w',encoding='utf-8') as f: f.write(cmd + "\n")


def assert_cmdline_uuid(dst_boot_fw: str, luks_uuid: str):
    p = os.path.join(dst_boot_fw,'cmdline.txt')
    if not os.path.isfile(p):
        raise RuntimeError('cmdline.txt missing')
    txt = open(p,'r',encoding='utf-8').read()
    if f'cryptdevice=UUID={luks_uuid}' not in txt:
        raise RuntimeError('cmdline.txt cryptdevice UUID mismatch')
    if 'root=/dev/mapper/rp5vg-root' not in txt:
        raise RuntimeError('cmdline.txt missing root mapper rp5vg-root')


def assert_crypttab_uuid(mnt: str, luks_uuid: str):
    ct = os.path.join(mnt, 'etc/crypttab')
    if not os.path.isfile(ct):
        raise RuntimeError('crypttab missing')
    txt = open(ct, 'r', encoding='utf-8').read()
    import re
    m = re.search(r'^cryptroot\s+UUID=([^\s]+)\s+', txt, re.M)
    if not m:
        raise RuntimeError('crypttab missing cryptroot line')
    if m.group(1) != luks_uuid:
        raise RuntimeError('crypttab UUID mismatch')
