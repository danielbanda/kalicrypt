
import os, subprocess, json, shlex, re, glob

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


def _canon(path: str) -> str:
    try:
        return os.path.realpath(path)
    except Exception:
        return path


def _first_line(text: str) -> str:
    if not text:
        return ""
    return text.splitlines()[0].strip()


def _command_output(cmd: list[str]) -> str:
    res = _run(cmd, check=False)
    if res.get("rc", 1) == 0 and res.get("out"):
        return _first_line(res["out"])
    return ""


def _findmnt_source(mountpoint: str) -> str:
    res = _run(["findmnt", "-no", "SOURCE", mountpoint], check=True)
    if res.get("rc") != 0 or not res.get("out"):
        raise RuntimeError(f"unable to determine source for mountpoint: {mountpoint}")
    return _first_line(res["out"])


def _fstype_of(device: str) -> str:
    for cmd in (["blkid", "-s", "TYPE", "-o", "value", device], ["lsblk", "-no", "FSTYPE", device]):
        out = _command_output(cmd)
        if out:
            return out
    return ""


def _uuid_of(device: str) -> str:
    for cmd in (["blkid", "-s", "UUID", "-o", "value", device], ["lsblk", "-no", "UUID", device]):
        out = _command_output(cmd)
        if out:
            return out
    return ""


def verify_sources(
    root_mount: str,
    boot_mount: str,
    esp_mount: str,
    expected_root: str,
    expected_boot: str,
    expected_esp: str,
) -> dict:
    result = {"ok": True, "sources": {}}
    checks = (
        ("root", root_mount, expected_root),
        ("boot", boot_mount, expected_boot),
        ("esp", esp_mount, expected_esp),
    )
    for label, mountpoint, expected in checks:
        actual_source = _canon(_findmnt_source(mountpoint))
        expected_source = _canon(expected)
        matches = actual_source == expected_source
        result["sources"][label] = {
            "mountpoint": mountpoint,
            "actual": actual_source,
            "expected": expected_source,
            "matches": matches,
        }
        if not matches:
            raise RuntimeError(f"{label} source mismatch: {actual_source} vs {expected_source}")
    return result


def verify_fs_and_uuid(
    p1: str,
    p2: str,
    p3: str,
    exp_uuid_p1: str | None = None,
    exp_uuid_p2: str | None = None,
    exp_uuid_luks: str | None = None,
) -> dict:
    result = {
        "ok": True,
        "warnings": [],
        "partitions": {},
    }

    f1 = _fstype_of(p1)
    f2 = _fstype_of(p2)
    u1 = _uuid_of(p1)
    u2 = _uuid_of(p2)
    ul = _uuid_of(p3)

    if f1 != "vfat":
        raise RuntimeError(f"p1 fstype expected vfat got {f1 or 'none'}")
    if f2 != "ext4":
        raise RuntimeError(f"p2 fstype expected ext4 got {f2 or 'none'}")

    result["partitions"]["p1"] = {"fstype": f1, "uuid": u1, "expected_uuid": exp_uuid_p1}
    result["partitions"]["p2"] = {"fstype": f2, "uuid": u2, "expected_uuid": exp_uuid_p2}
    result["partitions"]["luks"] = {"uuid": ul, "expected_uuid": exp_uuid_luks}

    if exp_uuid_p1 and u1 != exp_uuid_p1:
        result["warnings"].append(f"p1 uuid differs: {u1} vs {exp_uuid_p1}")
    if exp_uuid_p2 and u2 != exp_uuid_p2:
        result["warnings"].append(f"p2 uuid differs: {u2} vs {exp_uuid_p2}")
    if exp_uuid_luks and ul != exp_uuid_luks:
        result["warnings"].append(f"luks uuid differs: {ul} vs {exp_uuid_luks}")

    return result


def verify_triplet(
    mnt_root: str,
    esp_subdir: str,
    vg_name: str,
    lv_name: str,
    expected_luks_uuid: str | None = None,
) -> dict:
    result = {
        "ok": True,
        "warnings": [],
    }

    cmd_path = os.path.join(mnt_root, esp_subdir, "cmdline.txt")
    crypttab_path = os.path.join(mnt_root, "etc", "crypttab")
    fstab_path = os.path.join(mnt_root, "etc", "fstab")
    esp_dir = os.path.join(mnt_root, esp_subdir)

    for path in (cmd_path, crypttab_path, fstab_path):
        if not os.path.exists(path):
            raise RuntimeError(f"missing required file: {path}")

    cmd_text = _read(cmd_path)
    if expected_luks_uuid:
        token = f"cryptdevice=UUID={expected_luks_uuid}:cryptroot"
        if token not in cmd_text:
            result["warnings"].append("cmdline cryptdevice does not match expected LUKS UUID")
    if "root=/dev/mapper/" not in cmd_text:
        result["warnings"].append("cmdline missing root mapper token")
    result["cmdline"] = {"path": cmd_path, "text": cmd_text}

    crypttab_text = _read(crypttab_path)
    if not re.search(r"^cryptroot\s+UUID=", crypttab_text, re.M):
        raise RuntimeError("crypttab missing cryptroot line")
    result["crypttab"] = {"path": crypttab_path, "text": crypttab_text}

    fstab_text = _read(fstab_path)
    mapper_pattern = rf"/dev/mapper/{re.escape(vg_name)}-{re.escape(lv_name)}\s+/\s+ext4"
    if not re.search(mapper_pattern, fstab_text):
        raise RuntimeError("fstab missing root mapper line")
    result["fstab"] = {"path": fstab_path, "text": fstab_text}

    initramfs_glob = os.path.join(esp_dir, "initramfs_*")
    initramfs_matches = glob.glob(initramfs_glob)
    if not initramfs_matches:
        raise RuntimeError("initramfs image missing under ESP")
    result["initramfs"] = {"matches": initramfs_matches}

    return result

def nvme_boot_verification(device, esp_mb=None, boot_mb=None, passphrase_file=None, mnt_root="/mnt/nvme", mnt_esp="/mnt/esp"):
    res = {"steps": [], "ok": True}
    p1, p2, p3 = f"{device}p1", f"{device}p2", f"{device}p3"

    step = {"name": "uuids_and_cmdline", "checks": {}}
    step["checks"]["blkid_p1"] = _run(["blkid", p1])
    step["checks"]["blkid_p2"] = _run(["blkid", p2])
    step["checks"]["blkid_p3"] = _run(["blkid", p3])
    luks_check = _run(["cryptsetup", "luksUUID", p3])
    luks_uuid = (luks_check.get("out") or "").strip()
    step["checks"]["luks_uuid"] = luks_check
    cmdline_path = f"{mnt_root}/boot/firmware/cmdline.txt"
    cmdline_text = _read(cmdline_path).strip()
    cmdline_expected = (
        f"cryptdevice=UUID={luks_uuid}:cryptroot "
        "root=/dev/mapper/rp5vg-root "
        "rootfstype=ext4 rootwait"
    )
    step["checks"]["cmdline_preview"] = {
        "path": cmdline_path,
        "text": cmdline_text,
        "expected": cmdline_expected,
        "matches": cmdline_text == cmdline_expected,
    }
    res["steps"].append(step)

    step = {"name": "initramfs_modules", "checks": {}}
    step["checks"]["lsinitramfs"] = _run(["sh", "-lc", f"lsinitramfs {mnt_root}/boot/firmware/initramfs_2712 | egrep 'dm|crypt|lvm' || true"])
    res["steps"].append(step)

    step = {"name": "crypttab_fstab_consistency", "checks": {}}
    crypttab_path = f"{mnt_root}/etc/crypttab"
    fstab_path = f"{mnt_root}/etc/fstab"
    crypttab_text = _read(crypttab_path).strip()
    fstab_text = _read(fstab_path)
    expected_key = passphrase_file if passphrase_file else "none"
    crypttab_expected = f"cryptroot UUID={luks_uuid}  {expected_key}"
    step["checks"]["crypttab"] = {
        "path": crypttab_path,
        "text": crypttab_text,
        "expected": crypttab_expected,
        "matches": crypttab_text == crypttab_expected,
    }
    expected_fstab_root = "/dev/mapper/rp5vg-root  /  ext4  defaults  0  1"
    fstab_lines = [ln.strip() for ln in fstab_text.splitlines() if ln.strip()]
    step["checks"]["fstab"] = {
        "path": fstab_path,
        "text": fstab_text,
        "expected_root_entry": expected_fstab_root,
        "matches": expected_fstab_root in fstab_lines,
    }
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

    res["templates"] = {
        "cmdline": cmdline_expected,
        "crypttab": crypttab_expected,
        "fstab_root": expected_fstab_root,
    }

    return res
