"""Device probing & holder management (Phase 1, dry-run safe)."""
from __future__ import annotations

import json
from .model import DeviceMap
from .executil import run, udev_settle, trace


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

    # Probing is a read-only inspection operation.  Even during global dry-run
    # flows we still execute ``lsblk`` so that subsequent steps have accurate
    # device information to work with.
    udev_settle()
    result = run([
        "lsblk",
        "-J",
        "-o",
        "NAME,PATH,TYPE,PARTLABEL",
        device,
    ], check=True, dry_run=False)

    try:
        payload = json.loads(result.out or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse lsblk output for {device}: {exc}") from exc

    devices = payload.get("blockdevices") or []
    node = None
    for entry in devices:
        if entry.get("path") == device or entry.get("name") == device.rsplit("/", 1)[-1]:
            node = entry
            break

    if node is None:
        raise SystemExit(f"lsblk did not report device {device}")

    parts = [child for child in (node.get("children") or []) if child.get("type") == "part"]
    # Sort by name to ensure nvme0n1p1 < nvme0n1p2 < nvme0n1p3, even if lsblk
    # returns an arbitrary order.
    parts.sort(key=lambda c: c.get("name", ""))

    p1 = parts[0].get("path") or f"{device}p1"
    p2 = parts[1].get("path") or f"{device}p2"
    p3 = parts[2].get("path") or f"{device}p3"

    trace("devices.probe", device=device, p1=p1, p2=p2, p3=p3, dry_run=dry_run)

    return DeviceMap(device=device, p1=p1, p2=p2, p3=p3)

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
