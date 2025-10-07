"""Mount helpers (Phase 5.1)."""
from .model import Mounts
from .executil import run, udev_settle, trace
from .devices import probe

def _blkid(path: str) -> str:
    r = run(["blkid","-s","TYPE","-o","value", path], check=False)
    return (r.out or "").strip()

def _ensure_fs(dev: str, fstype: str, label: str = None, *, destructive: bool = True):
    """Ensure the target block device has the expected filesystem.

    When ``destructive`` is ``False`` the helper acts as a guard instead of
    provisioning a fresh filesystem.  This protects flows such as
    ``--do-postcheck`` where we must *only* observe an existing installation.
    In that mode we merely verify the detected filesystem type and abort if the
    expectation is not met.
    """

    cur = _blkid(dev)
    if cur == fstype:
        return

    if not destructive:
        raise SystemExit(
            f"refusing to format {dev}: expected {fstype!r}, detected {cur!r}"
        )
    if fstype == "vfat":
        args = ["mkfs.vfat","-F","32"]
        if label: args += ["-n", label]
        run(args + [dev], check=True, timeout=60.0)
    elif fstype == "ext4":
        args = ["mkfs.ext4","-F"]
        if label: args += ["-L", label]
        # pre-clean stale signatures and let udev settle
        run(["wipefs", "-a", dev], check=True, timeout=60.0)
        run(["udevadm", "settle"], check=True, timeout=60.0)
        run(args + [dev], check=True, timeout=360.0)
    else:
        raise SystemExit(f"Unsupported mkfs type: {fstype}")
    udev_settle()

def _mount(dev: str, dirpath: str, opts: list[str] = None):
    run(["mkdir","-p", dirpath], check=False)
    cmd = ["mount"]
    if opts: cmd += ["-o", ",".join(opts)]
    cmd += [dev, dirpath]
    run(cmd, check=True)
    udev_settle()

def mount_targets(
    device: str,
    dry_run: bool=False,
    *,
    destructive: bool = True,
) -> Mounts:
    dm = probe(device, dry_run=dry_run)
    mnt = "/mnt/nvme"
    boot = f"{mnt}/boot"
    esp = f"{boot}/firmware"

    # Ensure filesystems exist
    _ensure_fs(dm.p1, "vfat", label="EFI", destructive=destructive)
    _ensure_fs(dm.p2, "ext4", label="boot", destructive=destructive)
    # Root LV is fixed name
    root_dev = "/dev/mapper/rp5vg-root"
    _ensure_fs(root_dev, "ext4", label="root", destructive=destructive )

    # Mount in correct order
    _mount(root_dev, mnt)
    _mount(dm.p2, boot)
    _mount(dm.p1, esp, opts=["umask=0077"])  # secure ESP
    return Mounts(mnt=mnt, boot=boot, esp=esp)


def bind_mounts(mnt: str, dry_run: bool=False):
    # Ensure necessary mountpoints exist before bind-mounting
    for sub in ("/dev", "/proc", "/sys", "/run"):
        run(["mkdir","-p", f"{mnt}{sub}"], check=False, dry_run=dry_run)
    # Bind the live system dirs into the target for chroot operations
    for p in ("/dev","/proc","/sys","/run"):
        trace("bind_mount", src=p, dst=f"{mnt}{p}")
        run(["mount","--bind", p, f"{mnt}{p}"], check=False, dry_run=dry_run)


def unmount_all(mnt: str, force: bool=True, dry_run: bool=False):
    run(["sync"], check=False)
    for p in ("/proc","/sys","/dev"):
        run(["umount","-l", f"{mnt}{p}"], check=False)
    for p in (f"{mnt}/boot/firmware", f"{mnt}/boot", mnt):
        run(["umount","-l", p], check=False)
    udev_settle()



def assert_mount_sources(mnt: str, boot: str, esp: str, root_dev: str, boot_dev: str, esp_dev: str):
    def src(path):
        out = (run(["findmnt","-no","SOURCE", path], check=False).out or "")
        # findmnt sometimes prints extra newlines in stacked bind cases; pick the last non-empty line
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return lines[-1] if lines else ""

    def canon(dev):
        out = (run(["readlink","-f", dev], check=False).out or "").strip()
        return out if out else dev

    def uuid(dev):
        c = canon(dev)
        r = run(["blkid","-s","UUID","-o","value", c], check=False)
        txt = (r.out or "").strip()
        return txt

    s_root, s_boot, s_esp = src(mnt), src(boot), src(esp)

    # Quick exact equality short-circuit
    if s_root == root_dev and s_boot == boot_dev and s_esp == esp_dev:
        return

    pairs = [
        ("root", s_root, root_dev),
        ("boot", s_boot, boot_dev),
        ("esp",  s_esp,  esp_dev),
    ]

    mismatches = []
    for label, actual, expected in pairs:
        a_can, e_can = canon(actual), canon(expected)
        if a_can == e_can:
            continue
        a_uuid, e_uuid = uuid(actual), uuid(expected)
        if a_uuid and e_uuid and a_uuid == e_uuid:
            continue
        mismatches.append((label, actual, expected, a_can, e_can, a_uuid, e_uuid))

    if mismatches:
        parts = []
        for label, a, e, ac, ec, au, eu in mismatches:
            parts.append(f"{label}: actual={a} expected={e} | canon={ac} vs {ec} | uuid={au} vs {eu}")
        raise SystemExit("mount sources mismatch: " + " ; ".join(parts))
