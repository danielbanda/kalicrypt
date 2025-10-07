"""Device probing & holder management (Phase 1, dry-run safe)."""
from .model import DeviceMap
from .executil import run, udev_settle

def probe(device: str, dry_run: bool=False, read_only: bool | None = None) -> DeviceMap:
    """Probe the target disk layout.

    Historically this helper accepted a ``read_only`` flag.  Older call sites
    in the provisioning workflow may still use that keyword, so accept it as an
    alias for ``dry_run`` to remain backwards compatible with those entry
    points.  The probing logic is read-only by nature, so the value does not
    currently influence behaviour, but keeping the parameter prevents runtime
    ``TypeError`` crashes when invoking the CLI with versions that still pass
    ``read_only``.
    """

    if read_only is not None:
        dry_run = read_only

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
