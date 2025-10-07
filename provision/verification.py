
import os, subprocess, json, shlex

_PRIVILEGED_BINARIES = {"cryptsetup"}


def _needs_sudo(cmd_list: list[str]) -> bool:
    if not cmd_list:
        return False
    if cmd_list[0] == "sudo":
        return False
    if os.geteuid() == 0:
        return False
    return cmd_list[0] in _PRIVILEGED_BINARIES


def _run(cmd, check=False):
    if isinstance(cmd, str):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = list(cmd)
    if _needs_sudo(cmd_list):
        cmd_list = ["sudo"] + cmd_list
    proc = subprocess.run(cmd_list, capture_output=True, text=True)
    return {
        "cmd": cmd_list,
        "rc": proc.returncode,
        "out": proc.stdout.strip(),
        "err": proc.stderr.strip(),
        "ok": (proc.returncode == 0) if check else True,
    }

def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        return f"<read-failed: {e}>"

def nvme_boot_verification(device, esp_mb=None, boot_mb=None, passphrase_file=None, mnt_root="/mnt/nvme", mnt_esp="/mnt/esp"):
    res = {"steps": [], "ok": True}
    p1, p2, p3 = f"{device}p1", f"{device}p2", f"{device}p3"

    step = {"name": "uuids_and_cmdline", "checks": {}}
    step["checks"]["blkid_p1"] = _run(["blkid", p1])
    step["checks"]["blkid_p2"] = _run(["blkid", p2])
    step["checks"]["blkid_p3"] = _run(["blkid", p3])
    step["checks"]["luks_uuid"] = _run(["cryptsetup", "luksUUID", p3])
    step["checks"]["cmdline_preview"] = {"path": f"{mnt_root}/boot/firmware/cmdline.txt", "text": _read(f"{mnt_root}/boot/firmware/cmdline.txt")}
    res["steps"].append(step)

    step = {"name": "initramfs_modules", "checks": {}}
    step["checks"]["lsinitramfs"] = _run(["sh", "-lc", f"lsinitramfs {mnt_root}/boot/firmware/initramfs_2712 | egrep 'dm|crypt|lvm' || true"])
    res["steps"].append(step)

    step = {"name": "crypttab_fstab_consistency", "checks": {}}
    step["checks"]["crypttab"] = {"path": f"{mnt_root}/etc/crypttab", "text": _read(f"{mnt_root}/etc/crypttab")}
    step["checks"]["fstab"] = {"path": f"{mnt_root}/etc/fstab", "text": _read(f"{mnt_root}/etc/fstab")}
    res["steps"].append(step)

    step = {"name": "esp_cmdline_compare", "checks": {}}
    for p in (p1, "/dev/mmcblk0p1"):
        if os.path.exists(p):
            os.makedirs(mnt_esp, exist_ok=True)
            mnt_ok = _run(["mount", p, mnt_esp])
            txt = _read(os.path.join(mnt_esp, "cmdline.txt"))
            _run(["umount", mnt_esp])
            step["checks"][p] = {"mount_rc": mnt_ok["rc"], "cmdline": txt.strip()}
    res["steps"].append(step)

    step = {"name": "initramfs_checksum", "checks": {}}
    step["checks"]["sha256sum"] = _run(["sh", "-lc", f"sha256sum {mnt_root}/boot/firmware/initramfs_2712 || true"])
    res["steps"].append(step)

    step = {"name": "dryrun_open_mount", "checks": {}}
    if passphrase_file and os.path.exists(passphrase_file):
        step["checks"]["cryptsetup_open"] = _run(["cryptsetup", "open", p3, "cryptroot", "--key-file", passphrase_file])
        step["checks"]["vgchange_ay"] = _run(["vgchange", "-ay", "rp5vg"])
        os.makedirs("/mnt/testroot", exist_ok=True)
        step["checks"]["mount_root"] = _run(["mount", "/dev/rp5vg/root", "/mnt/testroot"])
        step["checks"]["list_core"] = _run(["sh", "-lc", "ls /mnt/testroot/bin /mnt/testroot/etc | wc -l"])
        step["checks"]["umount_root"] = _run(["umount", "/mnt/testroot"])
        step["checks"]["vgchange_an"] = _run(["vgchange", "-an", "rp5vg"])
        step["checks"]["cryptsetup_close"] = _run(["cryptsetup", "close", "cryptroot"])
    else:
        step["note"] = "passphrase_file not provided or missing; skipped open/mount simulation"
    res["steps"].append(step)

    step = {"name": "cmdline_invariants", "checks": {}}
    cmdline_txt = _read(f"{mnt_root}/boot/firmware/cmdline.txt")
    step["checks"]["has_cryptdevice"] = "cryptdevice=UUID=" in cmdline_txt
    step["checks"]["has_mapper_root"] = "root=/dev/mapper/rp5vg-root" in cmdline_txt
    step["checks"]["no_partuuid"] = "PARTUUID=" not in cmdline_txt
    step["checks"]["has_rootwait"] = "rootwait" in cmdline_txt
    res["steps"].append(step)

    return res
