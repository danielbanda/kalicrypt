"""Device probing & holder management (Phase 1, dry-run safe)."""
from .model import DeviceMap
from .executil import run, udev_settle

def probe(device: str, dry_run: bool=False) -> DeviceMap:
    return DeviceMap(device=device, p1=f"{device}p1", p2=f"{device}p2", p3=f"{device}p3")

def swapoff_all(dry_run: bool=False):
    run(["swapoff","-a"], check=False, dry_run=dry_run)

def holders(dev: str, dry_run: bool=False) -> str:
    r = run(["fuser","-vm", dev], check=False, dry_run=dry_run)
    return r.out

def kill_holders(dev: str, dry_run: bool=False):
    run(["fuser","-vmk", dev], check=False, dry_run=dry_run)
    udev_settle()

def uuid_of(path: str, dry_run: bool=False) -> str:
    r = run(["blkid","-s","UUID","-o","value", path], check=False, dry_run=dry_run)
    return (r.out or "").strip()
