
"""Write fstab/crypttab/cmdline and validate (Phase 2)."""
import os, re, json, subprocess
from .executil import run

def write_fstab(mnt: str, p1_uuid: str, p2_uuid: str):
    fstab = os.path.join(mnt, 'etc/fstab')
    os.makedirs(os.path.dirname(fstab), exist_ok=True)
    lines = [
        f"UUID={p1_uuid}  /boot/firmware  vfat  defaults,uid=0,gid=0,umask=0077  0  1",
        f"UUID={p2_uuid}  /boot  ext4  defaults  0  2",
        "/dev/mapper/rp5vg-root  /  ext4  defaults  0  1",
    ]
    data = "\n".join(lines) + "\n"
    with open(fstab, 'w', encoding='utf-8') as f:
        f.write(data)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass

def write_crypttab(mnt: str, luks_uuid: str, passfile: str|None, keyscript_path: str|None=None):
    ct = os.path.join(mnt, 'etc/crypttab')
    os.makedirs(os.path.dirname(ct), exist_ok=True)
    key = passfile if passfile else 'none'
    if keyscript_path:
        key = f"{key} keyscript={keyscript_path}"
    line = f"cryptroot UUID={luks_uuid}  {key}\n"
    with open(ct, 'w', encoding='utf-8') as f:
        f.write(line)
        try:
            f.flush(); os.fsync(f.fileno())
        except Exception:
            pass

def _resolve_root_mapper(root_mapper: str | None, vg: str | None, lv: str | None) -> str:
    if root_mapper and root_mapper.strip():
        return root_mapper.strip()
    vg_name = (vg or 'rp5vg').strip() or 'rp5vg'
    lv_name = (lv or 'root').strip() or 'root'
    return f"/dev/mapper/{vg_name}-{lv_name}"


def write_cmdline(
    dst_boot_fw: str,
    luks_uuid: str,
    root_mapper: str | None = None,
    vg: str | None = None,
    lv: str | None = None,
):
    p = os.path.join(dst_boot_fw, 'cmdline.txt')
    mapper_path = _resolve_root_mapper(root_mapper, vg, lv)
    cmd_parts = [
        f"cryptdevice=UUID={luks_uuid}:cryptroot",
        f"root={mapper_path}",
        "rootfstype=ext4",
        "rootwait",
    ]
    cmd = " ".join(cmd_parts)
    if os.path.exists(p):
        try:
            txt = open(p, 'r', encoding='utf-8').read().strip()
        except Exception:
            txt = ''
        if txt == cmd:
            return
    with open(p, 'w', encoding='utf-8') as f:
        f.write(f"{cmd}\n")
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass


def assert_cmdline_uuid(dst_boot_fw: str, luks_uuid: str, root_mapper: str | None = None):
    p = os.path.join(dst_boot_fw,'cmdline.txt')
    if not os.path.isfile(p):
        raise RuntimeError('cmdline.txt missing')
    txt = open(p,'r',encoding='utf-8').read()
    if f'cryptdevice=UUID={luks_uuid}' not in txt:
        raise RuntimeError('cmdline.txt cryptdevice UUID mismatch')
    mapper_path = _resolve_root_mapper(root_mapper, None, None)
    if mapper_path not in txt:
        raise RuntimeError(f'cmdline.txt missing root mapper {mapper_path}')


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
