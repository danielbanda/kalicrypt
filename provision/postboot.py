"""Post-boot heartbeat installer."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from .executil import run, udev_settle


def _write_file(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(content)
        try:
            fh.flush()
            os.fsync(fh.fileno())
        except Exception:
            pass
    os.replace(tmp_path, path)
    os.chmod(path, mode)


def install_postboot_check(mnt_root: str) -> dict:
    if not mnt_root or mnt_root == "/":
        return {}

    mnt = Path(mnt_root)
    script = mnt / "usr/local/sbin/rp5-postboot-check"
    unit = mnt / "etc/systemd/system/rp5-postboot.service"

    (mnt / "var/log/rp5").mkdir(parents=True, exist_ok=True)
    (mnt / "usr/local/sbin").mkdir(parents=True, exist_ok=True)
    (mnt / "etc/systemd/system").mkdir(parents=True, exist_ok=True)

    payload_lines = [
        "#!/bin/sh",
        "set -eu",
        "ts=$(date -Is)",
        "mkdir -p /var/log/rp5",
        'printf \'{"ts":"%s","result":"POSTBOOT_OK"}\\n\' "$ts" >> /var/log/rp5/heartbeat.jsonl',
        "systemctl disable rp5-postboot.service >/dev/null 2>&1 || true",
        "exit 0",
        "",
    ]
    _write_file(script, "\n".join(payload_lines), 0o755)

    unit_lines = [
        "[Unit]",
        "Description=RP5 Post-boot Heartbeat",
        "After=multi-user.target",
        "",
        "[Service]",
        "Type=oneshot",
        "ExecStart=/usr/local/sbin/rp5-postboot-check",
        "RemainAfterExit=yes",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ]
    _write_file(unit, "\n".join(unit_lines), 0o644)

    wants_dir = mnt / "etc/systemd/system/multi-user.target.wants"
    wants_dir.mkdir(parents=True, exist_ok=True)
    run(["ln", "-sf", "../rp5-postboot.service", str(wants_dir / "rp5-postboot.service")], check=True)

    udev_settle()
    return {"script": str(script), "unit": str(unit)}


def remove_postboot_artifacts(mnt_root: str) -> Dict[str, Any]:
    if not mnt_root or mnt_root == "/":
        return {"artifacts": [], "skipped": True}

    mnt = Path(mnt_root)
    targets: List[Path] = [
        Path("usr/local/sbin/rp5-postboot-check"),
        Path("etc/systemd/system/rp5-postboot.service"),
        Path("etc/systemd/system/multi-user.target.wants/rp5-postboot.service"),
        Path("root/RP5_RECOVERY.md"),
    ]
    details: List[Dict[str, Any]] = []
    for rel in targets:
        path = mnt / rel
        path_str = str(path)
        existed = os.path.lexists(path_str)
        entry: Dict[str, Any] = {"path": path_str, "existed": existed, "removed": False}
        if not existed:
            details.append(entry)
            continue
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path_str, ignore_errors=False)
            else:
                path.unlink()
            entry["removed"] = True
        except FileNotFoundError:
            entry["removed"] = False
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)
        details.append(entry)
    summary: Dict[str, Any] = {"artifacts": details}
    summary["any_removed"] = any(item.get("removed") for item in details)
    return summary
