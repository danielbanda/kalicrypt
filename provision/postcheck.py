from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from .initramfs import verify_keyfile_in_image
from .verification import require_boot_surface_ok, verify_boot_surface


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _assert_eq(label: str, a: str, b: str):
    if a != b:
        raise RuntimeError(f"{label} mismatch: {a} != {b}")


def cleanup_pycache(mnt: str, subdir: str = "home/admin/rp5"):
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


def run_postcheck(
        mnt: str,
        luks_uuid: str,
        p1_uuid: str | None = None,
        *,
        keyfile_path: Optional[str] = None,
        initramfs_key_meta: Optional[Dict[str, Any]] = None,
        verbose: bool = False,
) -> dict:
    res = {"checks": [], "ok": True, "installed": {}}

    recovery_host = os.path.join(mnt, "root", "RP5_RECOVERY.md")
    recovery_target = "/root/RP5_RECOVERY.md"
    if not os.path.isfile(recovery_host):
        raise RuntimeError(f"recovery doc missing at {recovery_host}")
    res["installed"]["recovery_doc"] = {
        "host_path": recovery_host,
        "target_path": recovery_target,
        "exists": True,
    }

    heartbeat_script = os.path.join(mnt, "usr", "local", "sbin", "rp5-postboot-check")
    heartbeat_unit = os.path.join(mnt, "etc", "systemd", "system", "rp5-postboot.service")
    heartbeat_ok = os.path.isfile(heartbeat_script) and os.path.isfile(heartbeat_unit)
    res["installed"]["heartbeat"] = {
        "script": heartbeat_script,
        "unit": heartbeat_unit,
        "exists": heartbeat_ok,
    }
    if not heartbeat_ok:
        raise RuntimeError("postboot heartbeat not fully installed")

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

    boot_fw = os.path.join(mnt, "boot", "firmware")
    keyfile_result: Dict[str, Any] | None = None
    if keyfile_path:
        keyfile_result = {
            "path": keyfile_path,
            "crypttab_has_key_path": keyfile_path in txt,
        }
        if not keyfile_result["crypttab_has_key_path"]:
            res["checks"].append({"keyfile": keyfile_result})
            raise RuntimeError(f"crypttab missing keyfile path {keyfile_path}")
        meta = initramfs_key_meta or verify_keyfile_in_image(boot_fw, keyfile_path)
        keyfile_result["initramfs_has_keyfile"] = bool(meta.get("included"))
        keyfile_result["initramfs_meta"] = meta
        res["checks"].append({"keyfile": keyfile_result})
        if not keyfile_result["initramfs_has_keyfile"]:
            why = meta.get("error") or "initramfs missing keyfile entry"
            raise RuntimeError(why)
    elif initramfs_key_meta:
        keyfile_result = {
            "crypttab_has_key_path": False,
            "initramfs_has_keyfile": bool(initramfs_key_meta.get("included")),
            "initramfs_meta": initramfs_key_meta,
        }
        res["checks"].append({"keyfile": keyfile_result})

    # 2) boot firmware/initramfs verification
    boot_surface = verify_boot_surface(boot_fw, luks_uuid=luks_uuid)
    res["checks"].append({"boot_surface": boot_surface})
    require_boot_surface_ok(boot_surface)

    # 3) Optionally validate ESP UUID (if provided)
    if p1_uuid:
        fstab = _read(os.path.join(mnt, "etc/fstab"))
        if fstab:
            if p1_uuid not in fstab and "vfat" in fstab:
                raise RuntimeError("fstab missing ESP UUID mapping")
        res["checks"].append({"fstab": True})

    res["keyfile"] = keyfile_result
    res["ok"] = True
    return res


POSTCHECK_OK = "POSTCHECK_OK"


def _pc_verify_keyfile_in_image(image, rel='etc/cryptsetup-keys.d/cryptroot.key'):
    try:
        import subprocess
        out = subprocess.check_output(['lsinitramfs', image], text=True)
        rel = rel.lstrip('/')
        return any(line.strip()==rel for line in out.splitlines())
    except Exception:
        return False
