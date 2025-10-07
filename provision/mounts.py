"""Mount helpers (Phase 5.1)."""
from subprocess import CalledProcessError
import os
import stat
import time

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
    try:
        run(args + [dev], check=True, timeout=360.0)
    except CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or "").strip() or f"exit status {exc.returncode}"
        trace(
            "mounts.mkfs_error",
            device=dev,
            fstype=fstype,
            rc=exc.returncode,
            stderr=(exc.stderr or "").strip(),
            stdout=(exc.stdout or "").strip(),
        )
        raise RuntimeError(f"mkfs.{fstype} failed on {dev}: {msg}") from exc

def _ensure_fs(dev: str, fstype: str, label: str | None=None):
    _await_block_device(dev, timeout=15.0)
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

def _root_lv_path(dm: DeviceMap) -> str:
    """Return the mapper path backing the root logical volume.

    Historically the path was hard-coded throughout the provisioning
    workflow.  Centralising the computation makes it easier to support
    alternative volume group or logical volume names in the future and keeps
    the mount helpers in sync with the probing logic.
    """

    root_path = getattr(dm, "root_lv_path", None)
    if root_path:
        return root_path
    if dm.vg and dm.lv:
        return f"/dev/mapper/{dm.vg}-{dm.lv}"
    raise SystemExit("unable to determine root logical volume path from device map")


def _is_block_device(path: str) -> bool:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:  # noqa: PERF203 - surface unexpected stat failures
        trace("mounts.stat_error", path=path, error=str(exc))
        return False
    return stat.S_ISBLK(st.st_mode)


def _root_lv_exists(dm: DeviceMap) -> bool:
    """Return ``True`` when the root logical volume path is available.

    When verifying an existing installation the logical volume may already be
    active before the provisioning helpers get a chance to run ``vgchange``.
    ``lsblk`` provides the mapper path in that situation, so prefer the
    explicit ``root_lv_path`` attribute from the device map when present and
    fall back to deriving the path from the volume group and logical volume
    names.  Any ``SystemExit`` raised by :func:`_root_lv_path` bubbles up so
    callers can handle missing metadata consistently.
    """

    root_path = dm.root_lv_path or _root_lv_path(dm)
    return bool(root_path) and _is_block_device(root_path)


def _await_block_device(path: str, timeout: float = 10.0, settle: bool = True) -> None:
    """Wait until ``path`` resolves to a block device.

    Device-mapper nodes can take a short while to appear after LVM commands
    return.  Poll the filesystem for up to ``timeout`` seconds, asking udev to
    settle between attempts so follow-up operations (``mkfs``, ``mount``) do
    not fail spuriously.
    """

    deadline = time.monotonic() + timeout
    trace("mounts.await_block.start", path=path, timeout=timeout)
    while True:
        if _is_block_device(path):
            trace("mounts.await_block.ready", path=path)
            return
        now = time.monotonic()
        if now >= deadline:
            break
        trace("mounts.await_block.retry", path=path, remaining=max(0.0, deadline - now))
        if settle:
            udev_settle()
        time.sleep(0.1)

    if not os.path.exists(path):
        raise RuntimeError(
            f"block device {path!r} did not appear within {timeout:.1f}s"
        )
    raise RuntimeError(f"{path!r} exists but is not a block device")


def _activate_vg(dm: DeviceMap):
    """Ensure the volume group backing ``dm`` is active.

    ``vgchange`` occasionally fails with ``exit status 5`` immediately after
    the LUKS container is opened because the LVM metadata cache has not been
    refreshed yet.  Retry once after forcing a metadata scan so the
    post-check-only flow can continue rather than crashing.
    """

    if not dm.vg:
        return

    def _do_activate():
        run(["vgchange", "-ay", dm.vg], check=True)

    try:
        if _root_lv_exists(dm):
            return
        _do_activate()
    except CalledProcessError as exc:
        if exc.returncode != 5:
            raise
        trace(
            "mounts.vgchange_retry",
            vg=dm.vg,
            rc=exc.returncode,
            stderr=(exc.stderr or "").strip(),
        )
        run(["pvscan", "--cache"], check=False)
        run(["vgscan", "--cache"], check=False)
        try:
            if _root_lv_exists(dm):
                return
            _do_activate()
        except CalledProcessError as retry_exc:
            if _root_lv_exists(dm):
                return
            msg = retry_exc.stderr or retry_exc.stdout or str(retry_exc)
            raise RuntimeError(
                f"failed to activate volume group {dm.vg!r}: {msg.strip()}"
            ) from retry_exc


def mount_targets(device: str, dry_run: bool=False, destructive: bool=True) -> Mounts:
    dm: DeviceMap = probe(device, dry_run=dry_run)
    mnt = "/mnt/nvme"
    boot = f"{mnt}/boot"
    esp = f"{boot}/firmware"
    run(["mkdir","-p", mnt, boot, esp], check=True)
    # Bring the volume group online before touching any of the logical
    # volumes.  This ensures the mapper path is available even when the VG is
    # inactive (for example when provisioning over an existing install where
    # ``vgcreate``/``lvcreate`` are no-ops).
    _activate_vg(dm)
    root_lv = _root_lv_path(dm)
    _await_block_device(root_lv, timeout=15.0)
    udev_settle()
    # ensure fs only when destructive
    if destructive:
        _ensure_fs(dm.p1, "vfat", label="EFI")
        _ensure_fs(dm.p2, "ext4", label="boot")
        _ensure_fs(root_lv, "ext4", label="root")
    # mount (ro when non-destructive)
    ro_opts = ["ro"] if not destructive else None
    _mount(root_lv, mnt, fstype="ext4", opts=ro_opts)
    _mount(dm.p2, boot, fstype="ext4", opts=ro_opts)
    #_mount(dm.p1, esp, fstype="vfat", opts=(ro_opts or ["umask=0077"]))  # keep umask on rw too
    # Keep the ESP permissions tight even on read-only verification mounts.
    esp_opts = ["umask=0077"]
    if ro_opts:
        esp_opts = ro_opts + esp_opts
    _mount(dm.p1, esp, fstype="vfat", opts=esp_opts)
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
    root_exp = _root_lv_path(dm)
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
