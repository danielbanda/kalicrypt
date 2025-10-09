from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from typing import Dict

from .executil import run

_SIZE_UNITS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 1024,
    "kb": 1024,
    "ki": 1024,
    "kib": 1024,
    "m": 1024 ** 2,
    "mb": 1024 ** 2,
    "mi": 1024 ** 2,
    "mib": 1024 ** 2,
    "g": 1024 ** 3,
    "gb": 1024 ** 3,
    "gi": 1024 ** 3,
    "gib": 1024 ** 3,
    "t": 1024 ** 4,
    "tb": 1024 ** 4,
    "ti": 1024 ** 4,
    "tib": 1024 ** 4,
    "p": 1024 ** 5,
    "pb": 1024 ** 5,
    "pi": 1024 ** 5,
    "pib": 1024 ** 5,
}

_NUMBER_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*([A-Za-z]+)?")


def _parse_size_field(fragment: str):
    human = fragment.strip()
    normalized = human.replace(",", "")
    match = _NUMBER_RE.search(normalized)
    if not match:
        return human, None
    try:
        value = float(match.group(1))
    except ValueError:
        return human, None
    unit = (match.group(2) or "bytes").lower()
    unit = unit.rstrip("s")
    multiplier = _SIZE_UNITS.get(unit, 1)
    return human, int(round(value * multiplier))


def _parse_int(fragment: str):
    match = re.search(r"(-?\d[\d,]*)", fragment)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_float(fragment: str):
    match = re.search(r"(-?\d[\d,]*\.?\d*)", fragment)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_rsync_stats(text: str) -> dict:
    if not isinstance(text, str):
        return {}
    stats: Dict[str, object] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if "files transferred:" in lower:
            value = _parse_int(line.split(":", 1)[1])
            if value is not None and "files_transferred" not in stats:
                stats["files_transferred"] = value
        elif lower.startswith("total file size:"):
            _, numeric = _parse_size_field(line.split(":", 1)[1])
            if numeric is not None:
                stats["total_file_size_bytes"] = numeric
        elif lower.startswith("total transferred file size:"):
            _, numeric = _parse_size_field(line.split(":", 1)[1])
            if numeric is not None:
                stats["transferred_size_bytes"] = numeric
        elif lower.startswith("file list size:"):
            _, numeric = _parse_size_field(line.split(":", 1)[1])
            if numeric is not None:
                stats["file_list_size_bytes"] = numeric
        elif lower.startswith("total bytes sent:"):
            _, numeric = _parse_size_field(line.split(":", 1)[1])
            if numeric is not None:
                stats["bytes_sent_bytes"] = numeric
        elif lower.startswith("total bytes received:"):
            _, numeric = _parse_size_field(line.split(":", 1)[1])
            if numeric is not None:
                stats["bytes_received_bytes"] = numeric
        elif lower.startswith("sent ") and " bytes  received " in lower and " bytes/sec" in lower:
            rate_match = re.search(r"([0-9][0-9,\.]*)\s*bytes/sec", line, re.IGNORECASE)
            if rate_match:
                rate = _parse_float(rate_match.group(1))
                if rate is not None:
                    stats["throughput_bytes_per_sec"] = rate
            if "bytes_sent_bytes" not in stats:
                sent_match = re.search(r"sent\s+([0-9][0-9,\.]*\s*[A-Za-z]+)", line, re.IGNORECASE)
                if sent_match:
                    _, numeric = _parse_size_field(sent_match.group(1))
                    if numeric is not None:
                        stats["bytes_sent_bytes"] = numeric
            if "bytes_received_bytes" not in stats:
                recv_match = re.search(r"received\s+([0-9][0-9,\.]*\s*[A-Za-z]+)", line, re.IGNORECASE)
                if recv_match:
                    _, numeric = _parse_size_field(recv_match.group(1))
                    if numeric is not None:
                        stats["bytes_received_bytes"] = numeric
        elif lower.startswith("speedup is "):
            value_segment = lower.split("speedup is", 1)[1]
            value = _parse_float(value_segment)
            if value is not None:
                stats["speedup"] = value
    return stats


EXCLUDES = ["/proc", "/sys", "/dev", "/run", "/mnt", "/media", "/tmp", "/var/tmp",
            "/etc/cryptsetup-keys.d/***",
            "/etc/cryptsetup-initramfs/conf-hook"]


def rsync_root(dst_mnt: str, dry_run: bool = False, timeout_sec: int = 360, exclude_boot: bool = False):
    dst = dst_mnt.rstrip("/") + "/"
    rsync_path = shutil.which("rsync")
    start_time = time.perf_counter()
    retries = 0
    if rsync_path:
        base = [
            rsync_path,
            "-aHAXx",
            "--numeric-ids",
            "--delete-after",
            "--info=progress2",
            "--stats",
            "--itemize-changes",
        ]
        for e in EXCLUDES:
            base += ["--exclude", e]
        if exclude_boot:
            for e in ("/boot", "/boot/", "/boot/*", "/boot/firmware", "/boot/firmware/*", "home/admin/*"):
                base += ["--exclude", e]
        cmd = base + ["/", dst]
        try:
            result = run(cmd, check=True, dry_run=dry_run, timeout=timeout_sec)
            result.retries = retries
            return result
        except subprocess.CalledProcessError as e:
            if e.returncode in (23, 24):
                print(
                    f"[WARN] rsync completed with return code {e.returncode} (partial transfer/vanished files, file=sys.stderr). Continuing.",
                    file=sys.stderr,
                )
                e.duration = time.perf_counter() - start_time
                e.retries = retries
                return e
            raise
    # Fallback: cp -a (no delete, best effort)
    result = run(["cp", "-a", "/.", dst_mnt], check=True, dry_run=dry_run, timeout=timeout_sec)
    result.retries = retries
    if exclude_boot:
        for rel in ("boot", "boot/firmware"):
            run(["rm", "-rf", f"{dst_mnt.rstrip('/')}/{rel}"], check=False, dry_run=dry_run)
    return result


# RSYNC_FALLBACK_OK helper
def _rsync_with_fallback(run, cmd, src, dst):
    try:
        rc = subprocess.run(cmd, capture_output=True, text=True).returncode
        if rc in (0, 23, 24):
            return True
    except Exception:
        pass
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return True
