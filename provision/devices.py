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

    # Capture any logical volumes reported under the third partition so that we
    # can discover custom volume group or logical volume names when verifying
    # an existing installation.
    detected_vg = "rp5vg"
    detected_lv = "root"
    detected_root_mapper = None

    def _walk_children(node: dict) -> list[dict]:
        return list(node.get("children") or [])

    def _iter_lvm_nodes(node: dict):
        stack = _walk_children(node)
        while stack:
            child = stack.pop()
            if child.get("type") == "lvm":
                yield child
            stack.extend(_walk_children(child))

    if len(parts) >= 3:
        for child in _iter_lvm_nodes(parts[2]):
            mapper = child.get("path") or child.get("name") or ""
            if mapper and not mapper.startswith("/"):
                mapper = f"/dev/{mapper}"
            detected_root_mapper = mapper or detected_root_mapper
            name = child.get("name") or ""
            if name:
                # ``lsblk`` reports device-mapper names with the ``vg-lv``
                # format.  Volume group and logical volume identifiers encode
                # literal dashes as double dashes, so walk the string to locate
                # the separator that is not part of an escape sequence.
                sep = None
                idx = 0
                while idx < len(name):
                    if name[idx] != "-":
                        idx += 1
                        continue
                    if idx + 1 < len(name) and name[idx + 1] == "-":
                        idx += 2
                        continue
                    sep = idx
                    break
                if sep is not None:
                    vg_encoded = name[:sep]
                    lv_encoded = name[sep + 1:]
                    if vg_encoded:
                        detected_vg = vg_encoded.replace("--", "-")
                    if lv_encoded:
                        detected_lv = lv_encoded.replace("--", "-")
            if detected_root_mapper:
                break

    # Devices such as NVMe and MMC require a ``p`` separator before the
    # partition index (``nvme0n1p1``), while others like ``sda`` do not.
    base = device.rstrip("/") or device
    suffix = "p" if base[-1:].isdigit() else ""

    resolved = []
    missing = []
    for idx in range(3):
        if idx < len(parts):
            path = parts[idx].get("path") or parts[idx].get("name")
            if path and not path.startswith("/"):
                path = f"/dev/{path}"
        else:
            path = None
        if not path:
            path = f"{device}{suffix}{idx + 1}"
            missing.append(idx + 1)
        resolved.append(path)

    if missing:
        labels = [child.get("partlabel") or child.get("name") or child.get("path") for child in parts]
        trace(
            "devices.probe.missing_partitions",
            device=device,
            expected=3,
            found=len(parts),
            labels=labels,
            missing=missing,
            dry_run=dry_run,
        )

    p1, p2, p3 = resolved

    trace(
        "devices.probe",
        device=device,
        p1=p1,
        p2=p2,
        p3=p3,
        vg=detected_vg,
        lv=detected_lv,
        root_lv_path=detected_root_mapper,
        dry_run=dry_run,
    )

    return DeviceMap(
        device=device,
        p1=p1,
        p2=p2,
        p3=p3,
        vg=detected_vg,
        lv=detected_lv,
        root_lv_path=detected_root_mapper,
    )

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
