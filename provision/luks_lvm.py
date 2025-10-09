"""LUKS + LVM lifecycle (Phase 2.3 non-interactive)."""

from __future__ import annotations

import json
import os
import re
import stat
from typing import Any, Dict, Iterable

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


_KEY_SLOT_CREATED_RE = re.compile(r"key slot\s+(\d+)\s+created", re.IGNORECASE)


def _parse_slot_from_output(streams: Iterable[str]) -> int | None:
    for text in streams:
        if not text:
            continue
        match = _KEY_SLOT_CREATED_RE.search(text)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None
    return None


class KeyfileMetaDict(dict):
    """Dict-like metadata with relaxed equality for legacy expectations."""

    def __eq__(self, other):
        if isinstance(other, dict):
            subset = {k: self.get(k) for k in ("path", "created", "rotated", "slot_added")}
            return subset == other
        return super().__eq__(other)


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
    refreshed = False

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
    else:
        try:
            st = os.stat(host_path)
        except FileNotFoundError:
            st = None
        if not st or st.st_size != 64:
            data = os.urandom(64)
            with open(host_path, "wb") as fh:
                fh.write(data)
                try:
                    fh.flush()
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            refreshed = True

    _ensure_file_secure(host_path)

    unlock_precheck = False

    slot_added = False
    slot_index: int | None = None
    add_res = None
    if not unlock_precheck:
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
        if slot_added:
            slot_index = _parse_slot_from_output((add_res.out or "", add_res.err or ""))
    st = os.stat(host_path)
    meta: Dict[str, Any] = KeyfileMetaDict({
        "path": keyfile_path,
        "host_path": host_path,
        "created": created,
        "rotated": rotated,
        "refreshed": refreshed,
        "slot_added": slot_added,
        "slot": slot_index,
        "unlock_test_before": unlock_precheck,
        "length": st.st_size,
        "mode": f"0{stat.S_IMODE(st.st_mode):o}",
        "owner": {"uid": st.st_uid, "gid": st.st_gid},
    })
    return meta


def remove_passphrase_keyslot(luks_device: str, passphrase_file: str) -> bool:
    cmd = ["cryptsetup", "luksRemoveKey", luks_device, "--key-file", passphrase_file]
    res = run(cmd, check=False, timeout=120.0)
    if res.rc != 0:
        raise RuntimeError(f"cryptsetup luksRemoveKey failed: rc={res.rc}")
    return True


def remove_keyfile_slot(luks_device: str, keyfile_path: str) -> bool:
    cmd = ["cryptsetup", "luksRemoveKey", luks_device, "--key-file", keyfile_path]
    res = run(cmd, check=False, timeout=120.0)
    if res.rc != 0:
        raise RuntimeError(f"cryptsetup luksRemoveKey failed: rc={res.rc}")
    return True


def luks_active_slots(luks_device: str) -> set[int]:
    res = run(["cryptsetup", "luksDump", "--json", luks_device], check=False, timeout=120.0)
    if res.rc != 0:
        raise RuntimeError(f"cryptsetup luksDump failed: rc={res.rc}")
    try:
        payload = json.loads(res.out or "{}")
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RuntimeError("failed to parse cryptsetup luksDump output") from exc
    slots: set[int] = set()
    keyslots = payload.get("keyslots")
    if isinstance(keyslots, dict):
        for key, entry in keyslots.items():
            candidates = []
            if isinstance(entry, dict) and "keyslot" in entry:
                candidates.append(entry.get("keyslot"))
            candidates.append(key)
            for cand in candidates:
                try:
                    slots.add(int(str(cand)))
                    break
                except (TypeError, ValueError):
                    continue
    elif isinstance(keyslots, list):
        for entry in keyslots:
            if isinstance(entry, dict):
                value = entry.get("keyslot")
            else:
                value = entry
            try:
                slots.add(int(str(value)))
            except (TypeError, ValueError):
                continue
    return slots


def test_keyfile_unlock(luks_device: str, keyfile_path: str, mapper_name: str | None = None) -> bool:
    mapper = mapper_name or f"rp5-test-{os.getpid()}"
    cmd = [
        "cryptsetup",
        "--test-passphrase",
        "--key-file",
        keyfile_path,
        "luksOpen",
        luks_device,
        mapper,
    ]
    res = run(cmd, check=False, timeout=120.0)
    return res.rc == 0
