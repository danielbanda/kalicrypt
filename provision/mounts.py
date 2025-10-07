"""Mount helpers (Phase 5.1)."""
from .model import Mounts, DeviceMap
from .executil import run, udev_settle, trace
from .devices import probe

def _blkid_type(path: str) -> str:
    r = run(["blkid","-s","TYPE","-o","value", path], check=False)
    return (r.out or "").strip()

def _mkfs(dev: str, fstype: str, label: str | None):
    args = [f"mkfs.{fstype}"]
    if fstype == "ext4":
        args += ["-F"]
    if label:
        if fstype == "vfat":
            args += ["-n", label]
        else:
            args += ["-L", label]
    run(args + [dev], check=True, timeout=120.0)

def _ensure_fs(dev: str, fstype: str, label: str | None=None):
    cur = _blkid_type(dev)
    if cur == fstype:
        return
    _mkfs(dev, fstype, label)

def _mount(dev: str, target: str, fstype: str | None=None, opts: list[str] | None=None):
    run(["mkdir","-p", target], check=True)
    cmd = ["mount"]
    if fstype: cmd += ["-t", fstype]
    if opts: cmd += ["-o", ",".join(opts)]
    cmd += [dev, target]
    run(cmd, check=True)

def _umount_all(paths: list[str]):
    for p in reversed(paths):
        run(["umount","-l", p], check=False)
    udev_settle()

def mount_targets(device: str, dry_run: bool=False, destructive: bool=True) -> Mounts:
    dm: DeviceMap = probe(device, read_only=dry_run)
    mnt = "/mnt/nvme"
    boot = f"{mnt}/boot"
    esp = f"{boot}/firmware"
    run(["mkdir","-p", mnt, boot, esp], check=True)
    # ensure fs only when destructive
    if destructive:
        _ensure_fs(dm.p1, "vfat", label="EFI")
        _ensure_fs(dm.p2, "ext4", label="boot")
        _ensure_fs("/dev/mapper/rp5vg-root", "ext4", label="root")
    # mount (ro when non-destructive)
    ro_opts = ["ro"] if not destructive else None
    _mount("/dev/mapper/rp5vg-root", mnt, fstype="ext4", opts=ro_opts)
    _mount(dm.p2, boot, fstype="ext4", opts=ro_opts)
    _mount(dm.p1, esp, fstype="vfat", opts=(ro_opts or ["umask=0077"]))  # keep umask on rw too
    return Mounts(mnt=mnt, boot=boot, esp=esp)


def _findmnt_source(path: str) -> str:
    r = run(["findmnt","-no","SOURCE", path], check=False)
    return (getattr(r, "out", "") or "").strip()

def bind_mounts(mnt: str, read_only: bool = False):
    # Bind basic system dirs into target root; remount ro if requested
    for p in ("dev", "proc", "sys", "run"):
        src = f"/{p}"
        dst = f"{mnt}/{p}"
        run(["mkdir","-p", dst], check=True)
        # Use --bind for consistency even for proc/sys; sufficient for verification flows
        run(["mount","--bind", src, dst], check=True)
        if read_only:
            run(["mount","-o","remount,ro", dst], check=False)

def unmount_all(mnt: str, boot: str | None = None, esp: str | None = None):
    # Unmount in reverse order; be lazy to avoid hard failures
    paths = [f"{mnt}/dev/pts", f"{mnt}/dev", f"{mnt}/proc", f"{mnt}/sys", f"{mnt}/run"]
    if esp: paths.append(esp)
    if boot: paths.append(boot)
    paths.append(mnt)
    for p in paths:
        run(["umount","-l", p], check=False)
    udev_settle()

def assert_mount_sources(dm: DeviceMap, mnt: str, boot: str, esp: str):
    # Compare actual mount backing devices vs expected from probe
    root_exp = "/dev/mapper/rp5vg-root"
    mnt_src = _findmnt_source(mnt)
    boot_src = _findmnt_source(boot)
    esp_src  = _findmnt_source(esp)
    mismatches = []
    if mnt_src and mnt_src != root_exp:
        mismatches.append(("root", mnt_src, root_exp))
    if boot_src and boot_src != dm.p2:
        mismatches.append(("boot", boot_src, dm.p2))
    if esp_src and esp_src != dm.p1:
        mismatches.append(("esp", esp_src, dm.p1))
    if mismatches:
        parts = [f"{label}: actual={a} expected={e}" for (label,a,e) in mismatches]
        raise SystemExit("mount sources mismatch: " + " ; ".join(parts))

def _umount(path:str):
    import subprocess
    subprocess.call(["umount","-Rfl", path])

def unmount_tracked(ms: "MountSet"):
    # Unmount binds first, then mounts in reverse
    for p in reversed(ms.binds):
        _umount(p)
    for p in reversed(ms.mounted_paths):
        _umount(p)

class MountSet:
    def __init__(self, mnt:str):
        self.mnt = mnt
        self.mounted_paths = []
        self.binds = []
