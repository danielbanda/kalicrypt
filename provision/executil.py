from __future__ import annotations

"""Lightweight subprocess wrapper and dry-run hook (skeleton)."""

import datetime as _dt
import json
import os
import shlex
import subprocess
import time
from typing import Sequence

from .paths import rp5_logs_dir


LOG_DIRS: list[str] | None = None
LOG_PATH: str | None = None


def _log_dirs() -> list[str]:
    if LOG_DIRS:
        return list(LOG_DIRS)
    return [
        rp5_logs_dir(),
        "/var/log/rp5",
        "/tmp/rp5-logs",
    ]


def _ensure_logger() -> str | None:
    global LOG_PATH
    if LOG_PATH:
        return LOG_PATH
    for d in _log_dirs():
        d_expanded = os.path.expanduser(d)
        try:
            os.makedirs(d_expanded, exist_ok=True)
            LOG_PATH = os.path.join(d_expanded, "ete_nvme.jsonl")
            return LOG_PATH
        except Exception:
            continue
    LOG_PATH = None
    return None


def resolve_log_path() -> str | None:
    """Return the active log path, creating directories when possible."""

    return _ensure_logger()


def _log_event(kind: str, cmd: list[str], rc: int = None, out: str = None, err: str = None, dur: float = None):
    ts = _dt.datetime.utcnow().isoformat() + "Z"
    line = {"ts": ts, "kind": kind, "cmd": cmd, "rc": rc, "dur": dur, "out": out, "err": err}
    path = _ensure_logger()
    try:
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
    except Exception:
        pass


class Result:
    def __init__(self, rc: int, out: str, err: str, duration: float):
        self.rc, self.out, self.err, self.duration = rc, out, err, duration


# --- RP5 TRACE LOGGING (default-enabled until ETE is ready) ---
LEVELS = {"TRACE": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "NONE": 100}
LOG_LEVEL = os.environ.get("RP5_LOG_LEVEL", "TRACE").upper()


def _write_jsonl(obj: dict):
    path = _ensure_logger()
    try:
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj) + "\n")
    except Exception:
        pass


def log(level: str, event: str, **fields):
    lvl = LEVELS.get(level.upper(), 100)
    cur = LEVELS.get(LOG_LEVEL, 100)
    if lvl < cur:
        return
    ts = _dt.datetime.now(_dt.UTC).isoformat() + "Z"
    rec = {"ts": ts, "level": level.upper(), "event": event}
    rec.update(fields)
    _write_jsonl(rec)


def trace(event: str, **fields):
    log("TRACE", event, **fields)


# --- end TRACE block ---

def run(
    cmd: Sequence[str],
    check: bool = True,
    dry_run: bool = False,
    timeout: float = 60.0,
    env: dict | None = None,
) -> Result:
    # TRACE: log command start
    try:
        trace('exec.start', cmd=list(cmd))
    except Exception:
        pass
    _log_event("exec", list(cmd))
    started = time.time()
    if dry_run:
        text = "DRY-RUN: " + " ".join(shlex.quote(c) for c in cmd)
        return Result(0, text, "", 0.0)
    try:
        env2 = (env or os.environ).copy()
        env2.setdefault('RP5_LOG_LEVEL', LOG_LEVEL)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env2)
    except subprocess.TimeoutExpired:
        try:
            subprocess.run(["udevadm", "settle"], check=False)
        except Exception:
            pass
        env2 = (env or os.environ).copy()
        env2.setdefault('RP5_LOG_LEVEL', LOG_LEVEL)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env2)
    dur = time.time() - started
    try:
        trace('exec.done', cmd=list(cmd), rc=proc.returncode, dur=dur)
    except Exception:
        pass
    _log_event("done", list(cmd), rc=proc.returncode, out=proc.stdout, err=proc.stderr, dur=dur)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
    return Result(proc.returncode, proc.stdout, proc.stderr, dur)


def udev_settle():
    try:
        subprocess.run(["udevadm", "settle"], check=False)
    except Exception:
        pass


def with_backoff(fn, tries: int = 3, base: float = 0.5, max_delay: float = 4.0):
    import time
    delay = base
    last = None
    for _ in range(max(1, tries)):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(delay)
            delay = min(max_delay, delay * 2)
    raise last


def append_jsonl(path: str, obj: dict):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass
