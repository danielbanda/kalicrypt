"""Post-boot heartbeat installer."""

from __future__ import annotations

import os
from pathlib import Path

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
