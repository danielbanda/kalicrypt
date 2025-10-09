"""Ensure/rebuild/verify initramfs in target root (Phase 2)."""
import os
import re
from pathlib import PurePosixPath
from typing import Any, Dict

from .executil import run
from .verification import verify_boot_surface

REQUIRED_PACKAGES = ("cryptsetup-initramfs", "lvm2", "initramfs-tools")
APT_TIMEOUT = 600
INITRAMFS_TIMEOUT = 360


def ensure_packages(mnt: str, dry_run: bool = False) -> Dict[str, Any]:
    """Install initramfs prerequisites inside the target root if missing."""

    stats: Dict[str, Any] = {"update": {}, "installs": [], "retries": 0}
    update = run(
        ["chroot", mnt, "/usr/bin/apt-get", "update"],
        check=False,
        dry_run=dry_run,
        timeout=APT_TIMEOUT,
    )
    stats["update"] = {"rc": update.rc, "duration_sec": getattr(update, "duration", None)}

    for pkg in REQUIRED_PACKAGES:
        pkg_stats: Dict[str, Any] = {"package": pkg}
        check_res = run(
            ["chroot", mnt, "/usr/bin/dpkg", "-s", pkg],
            check=False,
            dry_run=dry_run,
            timeout=APT_TIMEOUT,
        )
        pkg_stats.update({
            "present": check_res.rc == 0,
            "check_rc": check_res.rc,
            "check_duration_sec": getattr(check_res, "duration", None),
        })
        if check_res.rc != 0:
            install_res = run(
                ["chroot", mnt, "/usr/bin/apt-get", "-y", "install", pkg],
                check=False,
                dry_run=dry_run,
                timeout=APT_TIMEOUT,
            )
            pkg_stats.update(
                {
                    "installed": install_res.rc == 0,
                    "install_rc": install_res.rc,
                    "install_duration_sec": getattr(install_res, "duration", None),
                }
            )
            if install_res.rc != 0:
                stats["retries"] += 1
        stats["installs"].append(pkg_stats)
    return stats


def _ensure_crypttab_prompts(mnt: str) -> None:
    """Force crypttab to prompt for the passphrase (no baked-in key path)."""

    ct_path = os.path.join(mnt, "etc", "crypttab")
    if not os.path.isfile(ct_path):
        return
    with open(ct_path, "r", encoding="utf-8") as fh:
        original = fh.read()
    patched = re.sub(
        r"^(cryptroot\s+UUID=[0-9a-fA-F-]+)\s+\S+",
        r"\1 none",
        original,
        flags=re.M,
    )
    if patched != original:
        with open(ct_path, "w", encoding="utf-8") as fh:
            fh.write(patched)


def _detect_kernel_version(mnt: str) -> str:
    modules_dir = os.path.join(mnt, "lib", "modules")
    if not os.path.isdir(modules_dir):
        raise RuntimeError("initramfs: /lib/modules missing in target root")
    cands = [
        entry
        for entry in os.listdir(modules_dir)
        if os.path.isdir(os.path.join(modules_dir, entry))
    ]
    if not cands:
        raise RuntimeError("initramfs: no kernel modules found in target root")
    return sorted(cands)[0]


def rebuild(mnt: str, dry_run: bool = False, *, force_prompt: bool = True) -> Dict[str, Any]:
    if force_prompt:
        _ensure_crypttab_prompts(mnt)
    kver = _detect_kernel_version(mnt)

    telemetry: Dict[str, Any] = {"kernel": kver, "attempts": [], "retries": 0}

    res = run(
        ["chroot", mnt, "/usr/sbin/update-initramfs", "-c", "-k", kver],
        check=False,
        dry_run=dry_run,
        timeout=INITRAMFS_TIMEOUT,
    )
    telemetry["attempts"].append({"mode": "create", "rc": res.rc, "duration_sec": getattr(res, "duration", None)})
    if res.rc != 0:
        telemetry["retries"] += 1
        res = run(
            ["chroot", mnt, "/usr/sbin/update-initramfs", "-u", "-k", kver],
            check=True,
            dry_run=dry_run,
            timeout=INITRAMFS_TIMEOUT,
        )
        telemetry["attempts"].append({"mode": "update", "rc": res.rc, "duration_sec": getattr(res, "duration", None)})

    copy_res = run(
        ["chroot", mnt, "/bin/cp", "-f", f"/boot/initrd.img-{kver}", "/boot/firmware/initramfs_2712"],
        check=True,
        dry_run=dry_run,
        timeout=INITRAMFS_TIMEOUT,
    )
    telemetry["copy"] = {"rc": copy_res.rc, "duration_sec": getattr(copy_res, "duration", None)}

    list_res = run(
        [
            "chroot",
            mnt,
            "/usr/bin/lsinitramfs",
            "/boot/firmware/initramfs_2712",
        ],
        check=True,
        dry_run=dry_run,
        timeout=INITRAMFS_TIMEOUT,
    )
    telemetry["list"] = {"rc": list_res.rc, "duration_sec": getattr(list_res, "duration", None)}
    telemetry["image"] = os.path.join(mnt, "boot", "firmware", "initramfs_2712")

    return telemetry


def verify_keyfile_in_image(esp_dir: str, keyfile_path: str, image_name: str = "initramfs_2712") -> Dict[str, Any]:
    """Check that ``keyfile_path`` is present inside the assembled initramfs image."""

    key = PurePosixPath(keyfile_path)
    if key.is_absolute():
        try:
            rel_key = key.relative_to("/")
        except ValueError:
            rel_key = key
    else:
        rel_key = key
    relative_entry = rel_key.as_posix()
    normalized_entry = relative_entry.lstrip("./")
    if normalized_entry:
        relative_entry = normalized_entry
    try:
        secure_relative = rel_key.relative_to("etc/cryptsetup-keys.d")
        relative_entry = PurePosixPath("etc/cryptsetup-keys.d") / secure_relative
    except ValueError:
        relative_entry = PurePosixPath(relative_entry)
    basename = relative_entry.name
    image = os.path.join(esp_dir, image_name)
    target_entry = relative_entry.as_posix() or basename
    res = run(["lsinitramfs", image], check=False, timeout=INITRAMFS_TIMEOUT)
    listing = (res.out or "") if res.rc == 0 else ""
    lines = [line.strip() for line in listing.splitlines() if line.strip()]
    included = target_entry in lines or target_entry in listing
    result: Dict[str, Any] = {
        "image": image,
        "basename": basename,
        "target": target_entry,
        "relative_path": target_entry,
        "rc": res.rc,
        "included": included,
    }
    if res.rc == 0:
        result["lines"] = lines
    else:
        result["error"] = (res.err or res.out or "").strip()
    return result


def verify(dst_boot_fw: str, luks_uuid: str | None = None) -> Dict[str, Any]:
    return verify_boot_surface(dst_boot_fw, luks_uuid)


def newest_initrd(dst_boot_fw: str) -> str:
    cands = sorted([p for p in os.listdir(dst_boot_fw) if p.startswith('initramfs')], reverse=True)
    if not cands:
        raise RuntimeError("initramfs: no initramfs* found in /boot/firmware")
    return os.path.join(dst_boot_fw, cands[0])
