"""LUKS + LVM lifecycle (Phase 2.3 non-interactive)."""

from __future__ import annotations

import os
import stat
from typing import Any, Dict

from .executil import run, udev_settle


def _require_passfile(passphrase_file: str | None):
    if not passphrase_file:
        raise SystemExit("cryptsetup requires --passphrase-file; none provided.")


def format_luks(p3: str, passphrase_file: str | None, dry_run: bool = False):
    # Skip format if already LUKS
    probe = run(["cryptsetup", "isLuks", p3], check=False, dry_run=dry_run)
    if probe.rc == 0:
        return
    _require_passfile(passphrase_file)
    cmd = ["cryptsetup", "-q", "--batch-mode", "luksFormat", "--type", "luks2", "--label", "rp5root", "--key-file", passphrase_file, p3]
    run(cmd, check=True, dry_run=dry_run, timeout=360.0)
    udev_settle()


def open_luks(p3: str, name: str, passphrase_file: str | None, dry_run: bool = False):
    # If mapping exists, skip
    test = run(["sh", "-lc", f"[ -e /dev/mapper/{name} ] && echo yes || echo no"], check=False, dry_run=dry_run)
    if (test.out or "").strip() == "yes":
        return
    _require_passfile(passphrase_file)
    cmd = ["cryptsetup", "-q", "open", p3, name, "--key-file", passphrase_file, "--allow-discards"]
    run(cmd, check=True, dry_run=dry_run, timeout=60.0)
    udev_settle()


def make_vg_lv(vg: str, lv: str, size: str = "100%FREE", dry_run: bool = False):
    # Ensure PV exists on mapper
    run(["pvcreate", "-ff", "-y", "/dev/mapper/cryptroot"], check=False, dry_run=dry_run, timeout=60.0)
    run(["vgcreate", vg, "/dev/mapper/cryptroot"], check=False, dry_run=dry_run, timeout=60.0)
    run(["lvcreate", "-n", lv, "-l", size, vg], check=False, dry_run=dry_run, timeout=60.0)
    udev_settle()


def activate_vg(vg: str, dry_run: bool = False):
    """Activate logical volumes for ``vg`` if present."""

    run(["vgchange", "-ay", vg], check=False, dry_run=dry_run, timeout=60.0)
    udev_settle()


def deactivate_vg(vg: str, dry_run: bool = False):
    run(["vgchange", "-an", vg], check=False, dry_run=dry_run, timeout=60.0)


def close_luks(name: str, dry_run: bool = False):
    run(["cryptsetup", "close", name], check=False, dry_run=dry_run, timeout=60.0)


def _ensure_dir_secure(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except Exception:
        pass
    st = os.stat(path)
    if stat.S_IMODE(st.st_mode) != 0o700:
        raise PermissionError(f"directory {path} must have mode 0700")
    if st.st_uid != 0 or st.st_gid != 0:
        try:
            os.chown(path, 0, 0)
        except PermissionError as exc:
            raise PermissionError(f"directory {path} must be owned by root:root") from exc
        st = os.stat(path)
        if st.st_uid != 0 or st.st_gid != 0:
            raise PermissionError(f"directory {path} must be owned by root:root")


def _ensure_file_secure(path: str) -> None:
    try:
        os.chmod(path, 0o400)
    except Exception:
        pass
    st = os.stat(path)
    if stat.S_IMODE(st.st_mode) != 0o400:
        raise PermissionError(f"keyfile {path} must have mode 0400")
    if st.st_uid != 0 or st.st_gid != 0:
        try:
            os.chown(path, 0, 0)
        except PermissionError as exc:
            raise PermissionError(f"keyfile {path} must be owned by root:root") from exc
        st = os.stat(path)
        if st.st_uid != 0 or st.st_gid != 0:
            raise PermissionError(f"keyfile {path} must be owned by root:root")


def ensure_keyfile(
        mnt: str,
        keyfile_path: str,
        luks_device: str,
        passphrase_file: str,
        *,
        rotate: bool = False,
) -> Dict[str, Any]:
    """Ensure a keyfile exists on the target root and is enrolled in the LUKS device."""

    rel = keyfile_path.lstrip("/")
    host_path = os.path.normpath(os.path.join(mnt, rel))
    secure_root = os.path.normpath(os.path.join(mnt, "etc", "cryptsetup-keys.d"))
    if not host_path.startswith(secure_root + os.sep):
        raise ValueError("keyfile path must reside under /etc/cryptsetup-keys.d")

    directory = os.path.dirname(host_path)
    _ensure_dir_secure(directory)

    existed = os.path.exists(host_path)
    created = False
    rotated = False
    if rotate or not existed:
        data = os.urandom(64)
        with open(host_path, "wb") as fh:
            fh.write(data)
            try:
                fh.flush()
                os.fsync(fh.fileno())
            except OSError:
                pass
        created = not existed
        rotated = existed and rotate
    _ensure_file_secure(host_path)

    add_cmd = [
        "cryptsetup",
        "luksAddKey",
        luks_device,
        host_path,
        "--key-file",
        passphrase_file,
    ]
    add_res = run(add_cmd, check=False, timeout=120.0)
    combined = f"{(add_res.out or '').strip()}\n{(add_res.err or '').strip()}".lower()
    if add_res.rc != 0 and "already" not in combined:
        raise RuntimeError(f"cryptsetup luksAddKey failed: rc={add_res.rc}")
    slot_added = add_res.rc == 0
    return {"path": keyfile_path, "created": created, "rotated": rotated, "slot_added": slot_added}


def remove_passphrase_keyslot(luks_device: str, passphrase_file: str) -> bool:
    cmd = ["cryptsetup", "luksRemoveKey", luks_device, "--key-file", passphrase_file]
    res = run(cmd, check=False, timeout=120.0)
    if res.rc != 0:
        raise RuntimeError(f"cryptsetup luksRemoveKey failed: rc={res.rc}")
    return True
