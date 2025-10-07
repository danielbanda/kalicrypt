"""Mount helpers (Phase 5.1)."""
from subprocess import CalledProcessError
import contextlib
import os
import stat
import time

from .model import Mounts, DeviceMap
from .executil import run, udev_settle, trace
from .devices import probe


class MkfsError(RuntimeError):
    """Raised when destructive formatting fails or is unsafe."""

    def __init__(self, message: str, *, state: dict | None = None) -> None:
        super().__init__(message)
        self.state = state or {}


def _blkid_type(path: str) -> str:
    r = run(["blkid", "-s", "TYPE", "-o", "value", path], check=False)
    return (r.out or "").strip()


def _device_realpath(dev: str) -> str:
    try:
        return os.path.realpath(dev)
    except OSError:
        return dev


def _device_name(dev: str) -> str:
    return os.path.basename(_device_realpath(dev))


def _read_int(path: str) -> int | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
    except FileNotFoundError:
        return None
    except OSError as exc:  # noqa: PERF203 - capture unexpected sysfs errors
        trace("mounts.sysfs_read_error", path=path, error=str(exc))
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        trace("mounts.sysfs_parse_error", path=path, raw=text)
        return None


def _device_discard_capabilities(dev: str) -> dict:
    name = _device_name(dev)
    queue_dir = os.path.join("/sys/class/block", name, "queue")
    max_bytes = _read_int(os.path.join(queue_dir, "discard_max_bytes"))
    granularity = _read_int(os.path.join(queue_dir, "discard_granularity"))
    zeroes = _read_int(os.path.join(queue_dir, "discard_zeroes_data"))
    capabilities: dict[str, int | bool | None] = {
        "discard_max_bytes": max_bytes,
        "discard_granularity": granularity,
    }
    if zeroes is not None:
        capabilities["discard_zeroes_data"] = bool(zeroes)
    capabilities["supports_discard"] = bool(max_bytes and max_bytes > 0)
    return capabilities


def _device_ro(dev: str) -> bool:
    name = _device_name(dev)
    ro_path = os.path.join("/sys/class/block", name, "ro")
    try:
        with open(ro_path, "r", encoding="utf-8") as fh:
            return fh.read().strip() == "1"
    except FileNotFoundError:
        return False
    except OSError as exc:  # noqa: PERF203 - trace unexpected sysfs failures
        trace("mounts.preflight.ro_error", device=dev, path=ro_path, error=str(exc))
        return False


def _device_mountpoints(dev: str) -> list[str]:
    mountpoints: list[str] = []
    real = _device_realpath(dev)
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.strip().split()
                if not parts:
                    continue
                with contextlib.suppress(ValueError):
                    dash = parts.index("-")
                    source_idx = dash + 2
                    if source_idx >= len(parts):
                        continue
                    source = parts[source_idx]
                    if not source:
                        continue
                    try:
                        src_real = os.path.realpath(source)
                    except OSError:
                        src_real = source
                    if src_real == real:
                        mount_point = parts[4].replace("\\040", " ")
                        mountpoints.append(mount_point)
    except FileNotFoundError:
        return []
    except OSError as exc:  # noqa: PERF203 - ensure unexpected failures get surfaced via trace
        trace("mounts.preflight.mountinfo_error", device=dev, error=str(exc))
    return mountpoints


def _device_holders(dev: str) -> list[str]:
    name = _device_name(dev)
    holders_dir = os.path.join("/sys/class/block", name, "holders")
    try:
        return sorted(os.listdir(holders_dir))
    except FileNotFoundError:
        return []
    except OSError as exc:  # noqa: PERF203 - diagnostic trace
        trace("mounts.preflight.holders_error", device=dev, path=holders_dir, error=str(exc))
        return []


def _dmsetup_open_count(dev: str) -> int | None:
    candidates = [_device_realpath(dev), _device_name(dev)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            result = run(["dmsetup", "info", "-c", "--noheadings", "-o", "open", candidate], check=False)
        except FileNotFoundError:
            trace("mounts.preflight.dmsetup_missing")
            return None
        if result.rc == 0 and result.out:
            text = result.out.strip().splitlines()[-1]
            try:
                return int(text)
            except ValueError:
                trace("mounts.preflight.dmsetup_parse_error", device=dev, raw=text)
                return None
    return None


def _collect_device_state(dev: str) -> dict:
    state = {
        "device": dev,
        "realpath": _device_realpath(dev),
        "read_only": _device_ro(dev),
        "mountpoints": _device_mountpoints(dev),
        "holders": _device_holders(dev),
    }
    discard = _device_discard_capabilities(dev)
    if discard:
        state["discard_capabilities"] = discard
    open_count = _dmsetup_open_count(dev)
    if open_count is not None:
        state["dmsetup_open_count"] = open_count
    return state


def _preflight_errors(state: dict) -> list[str]:
    errors: list[str] = []
    if state.get("read_only"):
        errors.append("device is read-only")
    mountpoints = state.get("mountpoints") or []
    if mountpoints:
        mounts = ", ".join(sorted(mountpoints))
        errors.append(f"device is mounted at {mounts}")
    holders = state.get("holders") or []
    if holders:
        errors.append(f"device has holders: {', '.join(holders)}")
    open_count = state.get("dmsetup_open_count")
    if isinstance(open_count, int) and open_count > 0:
        errors.append(f"dmsetup open count is {open_count}")
    return errors


def _dd_zero_first_megabytes(dev: str, count: int = 8) -> dict:
    args = [
        "dd",
        "if=/dev/zero",
        f"of={dev}",
        "bs=1M",
        f"count={count}",
        "conv=fsync",
    ]
    result = run(args, check=False, timeout=max(120.0, count * 2.0))
    info = {
        "args": args,
        "rc": result.rc,
        "stdout": (result.out or "").strip(),
        "stderr": (result.err or "").strip(),
    }
    trace(
        "mounts.dd_zero", device=dev, rc=result.rc, stderr=info["stderr"], stdout=info["stdout"]
    )
    return info


def _wipe_device(dev: str, *, discard: bool = True) -> dict:
    wipe_info: dict[str, object] = {
        "discard_capabilities": _device_discard_capabilities(dev),
    }

    def _run_wipefs(*extra_args: str) -> None:
        result = run(["wipefs", "-a", *extra_args, dev], check=True, timeout=120.0)
        wipe_info["wipefs"] = {
            "args": ["wipefs", "-a", *extra_args, dev],
            "rc": result.rc,
            "stdout": (result.out or "").strip(),
            "stderr": (result.err or "").strip(),
        }

    try:
        _run_wipefs()
    except CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or "").strip() or f"exit status {exc.returncode}"
        # ``wipefs`` occasionally reports ``cannot flush modified buffers`` on
        # freshly created device-mapper nodes.  The metadata wipes succeed but
        # the follow-up flush fails while udev is still settling, causing the
        # provisioning flow to abort.  Retry with ``--no-sync`` so ``wipefs``
        # skips the flush step in this specific scenario.  Keep the fallback
        # narrowly scoped to avoid masking other unexpected errors.
        if "cannot flush modified buffers" in msg.lower():
            trace("mounts.wipefs_retry_no_sync", device=dev, message=msg)
            try:
                _run_wipefs("--no-sync")
            except CalledProcessError:
                raise MkfsError(
                    f"wipefs failed on {dev}: {msg}",
                    state=_collect_device_state(dev),
                ) from exc
            else:
                trace("mounts.wipefs_retry_no_sync_success", device=dev)
                msg = None
        if msg:
            raise MkfsError(
                f"wipefs failed on {dev}: {msg}",
                state=_collect_device_state(dev),
            ) from exc
    if not discard:
        return wipe_info

    capabilities = wipe_info.get("discard_capabilities") or {}
    supports_discard = bool(capabilities.get("supports_discard"))
    discard_args = ["blkdiscard", "-fv", dev]
    if supports_discard:
        result = run(discard_args, check=False, timeout=360.0)
        discard_info = {
            "args": discard_args,
            "rc": result.rc,
            "stdout": (result.out or "").strip(),
            "stderr": (result.err or "").strip(),
        }
        wipe_info["blkdiscard"] = discard_info
        if result.rc != 0:
            trace(
                "mounts.blkdiscard_failed",
                device=dev,
                rc=result.rc,
                stderr=discard_info["stderr"],
                stdout=discard_info["stdout"],
            )
            dd_info = _dd_zero_first_megabytes(dev)
            wipe_info["dd_zero"] = dd_info
            if dd_info["rc"] != 0:
                state = {**_collect_device_state(dev), "wipe": wipe_info}
                detail = dd_info.get("stderr") or dd_info.get("stdout") or f"rc {dd_info['rc']}"
                raise MkfsError(
                    f"zeroing {dev} failed: {detail}",
                    state=state,
                )
    else:
        trace("mounts.discard_unsupported", device=dev, capabilities=capabilities)
        dd_info = _dd_zero_first_megabytes(dev)
        wipe_info["dd_zero"] = dd_info
        if dd_info["rc"] != 0:
            state = {**_collect_device_state(dev), "wipe": wipe_info}
            detail = dd_info.get("stderr") or dd_info.get("stdout") or f"rc {dd_info['rc']}"
            raise MkfsError(
                f"zeroing {dev} failed: {detail}",
                state=state,
            )

    return wipe_info


def _dmesg_tail(lines: int = 120) -> list[str] | None:
    try:
        result = run(["dmesg", "-T"], check=False, timeout=10.0)
    except FileNotFoundError:
        trace("mounts.dmesg_missing")
        return None
    output = (result.out or "").splitlines()
    if not output:
        return []
    return output[-lines:]


def _lsblk_discard(dev: str) -> str | None:
    try:
        result = run(["lsblk", "-D", dev], check=False, timeout=10.0)
    except FileNotFoundError:
        trace("mounts.lsblk_missing")
        return None
    return (result.out or "").strip()


def _dmsetup_table_snapshot(dev: str) -> dict | None:
    try:
        result = run(["dmsetup", "table", dev], check=False, timeout=10.0)
    except FileNotFoundError:
        trace("mounts.dmsetup_missing")
        return {"error": "dmsetup not found"}
    return {
        "rc": result.rc,
        "stdout": (result.out or "").strip(),
        "stderr": (result.err or "").strip(),
    }


def _mkfs(dev: str, fstype: str, label: str | None):
    state = _collect_device_state(dev)
    state["fstype"] = fstype
    errors = _preflight_errors(state)
    if errors:
        raise MkfsError(
            f"refusing to format {dev}: " + "; ".join(errors),
            state=state,
        )

    try:
        wipe_info = _wipe_device(dev)
    except MkfsError as exc:
        exc_state = dict(exc.state or {})
        exc_state.setdefault("fstype", fstype)
        exc.state = exc_state
        raise

    args = [f"mkfs.{fstype}"]
    if fstype == "ext4":
        args += ["-F", "-E", "lazy_journal_init=1"]
    if label:
        if fstype == "vfat":
            args += ["-n", label]
        else:
            args += ["-L", label]

    attempts: list[dict[str, str | int]] = []
    delay = 0.5
    extra_variants: list[list[str]]
    if fstype == "ext4":
        extra_variants = [[], ["-O", "^metadata_csum_seed"]]
    else:
        extra_variants = [[]]
    for attempt in range(3):
        extra = extra_variants[min(attempt, len(extra_variants) - 1)]
        cmd = args + extra + [dev]
        try:
            run(cmd, check=True, timeout=360.0)
            trace("mounts.mkfs_success", device=dev, fstype=fstype, attempts=attempt + 1)
            return
        except CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or "").strip() or f"exit status {exc.returncode}"
            attempts.append({
                "rc": exc.returncode,
                "stderr": (exc.stderr or "").strip(),
                "stdout": (exc.stdout or "").strip(),
                "message": msg,
                "args": cmd,
            })
            trace(
                "mounts.mkfs_retry",
                device=dev,
                fstype=fstype,
                attempt=attempt + 1,
                rc=exc.returncode,
                stderr=(exc.stderr or "").strip(),
            )
            if attempt == 2:
                break
            udev_settle()
            time.sleep(delay)
            delay = min(4.0, delay * 2)

    raise MkfsError(
        f"mkfs.{fstype} failed on {dev}: {attempts[-1]['message'] if attempts else 'unknown error'}",
        state={
            **_collect_device_state(dev),
            "mkfs_attempts": attempts,
            "fstype": fstype,
            "wipe": wipe_info,
            "diagnostics": {
                "dmesg_tail": _dmesg_tail(),
                "lsblk_discard": _lsblk_discard(dev),
                "dmsetup_table": _dmsetup_table_snapshot(dev),
            },
        },
    )

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
