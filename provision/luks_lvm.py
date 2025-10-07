
"""LUKS + LVM lifecycle (Phase 2.3 non-interactive)."""
from .executil import run, udev_settle

def _require_passfile(passphrase_file: str|None):
    if not passphrase_file:
        raise SystemExit("cryptsetup requires --passphrase-file; none provided.")

def format_luks(p3: str, passphrase_file: str|None, dry_run: bool=False):
    # Skip format if already LUKS
    probe = run(["cryptsetup","isLuks", p3], check=False, dry_run=dry_run)
    if probe.rc == 0:
        return
    _require_passfile(passphrase_file)
    cmd = ["cryptsetup","-q","--batch-mode","luksFormat","--type","luks2","--label","rp5root","--key-file", passphrase_file, p3]
    run(cmd, check=True, dry_run=dry_run, timeout=360.0)
    udev_settle()

def open_luks(p3: str, name: str, passphrase_file: str|None, dry_run: bool=False):
    # If mapping exists, skip
    test = run(["sh","-lc", f"[ -e /dev/mapper/{name} ] && echo yes || echo no"], check=False, dry_run=dry_run)
    if (test.out or "").strip() == "yes":
        return
    _require_passfile(passphrase_file)
    cmd = ["cryptsetup","-q","open", p3, name, "--key-file", passphrase_file, "--allow-discards"]
    run(cmd, check=True, dry_run=dry_run, timeout=60.0)
    udev_settle()

def make_vg_lv(vg: str, lv: str, size: str="100%FREE", dry_run: bool=False):
    # Ensure PV exists on mapper
    run(["pvcreate","-ff","-y","/dev/mapper/cryptroot"], check=False, dry_run=dry_run, timeout=60.0)
    run(["vgcreate", vg, "/dev/mapper/cryptroot"], check=False, dry_run=dry_run, timeout=60.0)
    run(["lvcreate","-n", lv, "-l", size, vg], check=False, dry_run=dry_run, timeout=60.0)
    udev_settle()

def activate_vg(vg: str, dry_run: bool=False):
    """Activate logical volumes for ``vg`` if present."""

    run(["vgchange", "-ay", vg], check=False, dry_run=dry_run, timeout=60.0)
    udev_settle()

def deactivate_vg(vg: str, dry_run: bool=False):
    run(["vgchange","-an", vg], check=False, dry_run=dry_run, timeout=60.0)

def close_luks(name: str, dry_run: bool=False):
    run(["cryptsetup","close", name], check=False, dry_run=dry_run, timeout=60.0)
