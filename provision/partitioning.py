
"""GPT layout application & verification (Phase 2.2)."""
import re

from .executil import run, udev_settle

def _base_device(dev: str) -> str:
    # strip trailing partition number for nvme style
    return re.sub(r'p\d+$', '', dev)

def guard_not_live_root(target: str):
    root_src = run(["findmnt","-no","SOURCE","/"], check=False).out.strip()
    if root_src and _base_device(root_src) == _base_device(target):
        raise SystemExit(f"FATAL: target {target} shares base device with live root {root_src}")

def precleanup(device: str, dry_run: bool=False):
    run(["swapoff","-a"], check=False, dry_run=dry_run)
    # kill holders on device and parts
    for node in (device, device+"p1", device+"p2", device+"p3"):
        run(["fuser","-vmk", node], check=False, dry_run=dry_run)
        run(["umount","-l", node], check=False, dry_run=dry_run)
    for dm in ("cryptroot",):
        run(["dmsetup","remove","--retry", dm], check=False, dry_run=dry_run)
    run(["vgchange","-an","rp5vg"], check=False, dry_run=dry_run)
    udev_settle()

def reread(device: str, dry_run: bool=False):
    # Multiple methods to convince kernel to reread partition table
    run(["blockdev","--rereadpt", device], check=False, dry_run=dry_run)
    run(["partprobe", device], check=False, dry_run=dry_run)
    run(["partx","-u", device], check=False, dry_run=dry_run)
    run(["sh","-lc", f"command -v hdparm >/dev/null 2>&1 && hdparm -z {device} || true"], check=False, dry_run=dry_run)
    udev_settle()

def _create_with_sgdisk(device: str, esp_mb: int, boot_mb: int, dry_run: bool):
    cmds = [
        ["sgdisk","-Z", device],
        ["sgdisk","-n","1:0:+%dM"%esp_mb, "-t","1:ef00", device],
        ["sgdisk","-n","2:0:+%dM"%boot_mb, "-t","2:8300", device],
        ["sgdisk","-n","3:0:0", "-t","3:8309", device],
    ]
    for c in cmds:
        run(c, check=True, dry_run=dry_run, timeout=60.0)
    reread(device, dry_run=dry_run)

def _create_with_parted(device: str, esp_mb: int, boot_mb: int, dry_run: bool):
    # parted sizes in MiB; leave 1MiB at start for alignment
    run(["parted","-s", device, "mklabel","gpt"], check=True, dry_run=dry_run)
    run(["parted","-s", device, "mkpart","ESP","fat32","1MiB", f"{esp_mb+1}MiB"], check=True, dry_run=dry_run)
    run(["parted","-s", device, "set","1","esp","on"], check=False, dry_run=dry_run)
    start2 = esp_mb + 1
    end2 = start2 + boot_mb
    run(["parted","-s", device, "mkpart","boot","ext4", f"{start2}MiB", f"{end2}MiB"], check=True, dry_run=dry_run)
    run(["parted","-s", device, "mkpart","luks","ext4", f"{end2}MiB", "100%"], check=True, dry_run=dry_run)
    # ensure LUKS GUID on p3
    run(["sgdisk","-t","3:8309", device], check=False, dry_run=dry_run)
    reread(device, dry_run=dry_run)

def _have_three_parts(device: str, dry_run: bool=False) -> bool:
    out = run(["sgdisk","-p", device], check=False, dry_run=dry_run).out
    return bool(out and re.search(r"\n\s*1\s+|\n\s*2\s+|\n\s*3\s+", out))

def apply_layout(device: str, esp_mb: int, boot_mb: int, dry_run: bool=False):
    guard_not_live_root(device)
    precleanup(device, dry_run=dry_run)
    for p in (device+"p1", device+"p2", device+"p3"):
        run(["wipefs","-a", p], check=False, dry_run=dry_run)
    # Try sgdisk, fallback to parted, retry up to 3 times
    ok = False
    for attempt in range(3):
        try:
            _create_with_sgdisk(device, esp_mb, boot_mb, dry_run)
        except Exception:
            _create_with_parted(device, esp_mb, boot_mb, dry_run)
        reread(device, dry_run=dry_run)
        if _have_three_parts(device, dry_run=dry_run):
            ok = True
            break
        # backoff
        run(["sh","-lc","sleep 1"], check=False, dry_run=dry_run)
    if not ok:
        raise SystemExit(f"partitioning: failed to materialize 3 partitions on {device}")

def verify_layout(device: str, dry_run: bool=False):
    run(["sgdisk","-p", device], check=False, dry_run=dry_run)
