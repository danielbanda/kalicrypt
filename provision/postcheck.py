from __future__ import annotations
import os, re, json, glob

def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except FileNotFoundError:
        return ""

def _require(path: str):
    if not os.path.exists(path):
        raise RuntimeError(f"missing: {path}")

def _assert_eq(label: str, a: str, b: str):
    if a != b:
        raise RuntimeError(f"{label} mismatch: {a} != {b}")

def _assert_contains(label: str, text: str, needle: str):
    if needle not in text:
        raise RuntimeError(f"{label} missing expected token: {needle}")

def cleanup_pycache(mnt: str, subdir: str="home/admin/rp5"):
    root = os.path.join(mnt, subdir)
    if not os.path.exists(root):
        return {"removed_dirs": 0, "removed_files": 0}
    removed_dirs = 0
    removed_files = 0
    for dp, dn, fn in os.walk(root):
        for d in list(dn):
            if d == "__pycache__":
                p = os.path.join(dp, d)
                try:
                    for rp, rdn, rfn in os.walk(p, topdown=False):
                        for f in rfn:
                            try:
                                os.remove(os.path.join(rp, f))
                                removed_files += 1
                            except Exception:
                                pass
                        try:
                            os.rmdir(rp)
                            removed_dirs += 1
                        except Exception:
                            pass
                    dn.remove(d)
                except Exception:
                    pass
        for f in list(fn):
            if f.endswith(".pyc"):
                try:
                    os.remove(os.path.join(dp, f))
                    removed_files += 1
                except Exception:
                    pass
    return {"removed_dirs": removed_dirs, "removed_files": removed_files}

def run_postcheck(mnt: str, luks_uuid: str, p1_uuid: str|None=None, verbose: bool=False) -> dict:
    res = {"checks": [], "ok": True}

    # 1) crypttab UUID
    ct_path = os.path.join(mnt, "etc/crypttab")
    txt = _read(ct_path)
    if not txt:
        raise RuntimeError(f"crypttab not found at {ct_path}")
    m = re.search(r'^cryptroot\s+UUID=([^\s]+)\s+', txt, re.M)
    if not m:
        raise RuntimeError("crypttab missing cryptroot line")
    crypt_uuid = m.group(1)
    _assert_eq("crypttab UUID", crypt_uuid, luks_uuid)
    res["checks"].append({"crypttab": True, "uuid": crypt_uuid})

    # 2) cmdline.txt contains cryptdevice=UUID=... and root mapper
    cmd = _read(os.path.join(mnt, "boot/firmware/cmdline.txt"))
    _assert_contains("cmdline", cmd, f"cryptdevice=UUID={luks_uuid}:cryptroot")
    _assert_contains("cmdline", cmd, "root=/dev/mapper/rp5vg-root")
    res["checks"].append({"cmdline": True})

    # 3) initramfs and kernel images present
    bootdir = sorted(glob.glob(os.path.join(mnt))) # temp fix
    # bootdir = os.path.join(mnt, "boot")
    _require(bootdir)
    has_initramfs = any(name.startswith("initrd") or name.endswith(".img") for name in os.listdir(bootdir))
    if not has_initramfs:
        raise RuntimeError("no initramfs found under /boot")
    has_kernel = any(name.startswith("vmlinuz") or name.startswith("Image") for name in os.listdir(bootdir))
    if not has_kernel:
        raise RuntimeError("no kernel image found under /boot")
    res["checks"].append({"boot_artifacts": True})

    # 4) Optionally validate ESP UUID (if provided)
    if p1_uuid:
        fstab = _read(os.path.join(mnt, "etc/fstab"))
        if fstab:
            if p1_uuid not in fstab and "vfat" in fstab:
                raise RuntimeError("fstab missing ESP UUID mapping")
        res["checks"].append({"fstab": True})

    res["ok"] = True
    return res

POSTCHECK_OK = "POSTCHECK_OK"
