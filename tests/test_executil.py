import json
from types import SimpleNamespace

import pytest

from provision import executil


def test_log_event_creates_log(tmp_path, monkeypatch):
    monkeypatch.setattr(executil, "LOG_DIRS", [str(tmp_path)])
    monkeypatch.setattr(executil, "LOG_PATH", None, raising=False)
    executil._log_event("exec", ["echo", "hi"], rc=0, out="ok", err=None, dur=0.1)
    log_file = tmp_path / "ete_nvme.jsonl"
    assert log_file.exists()
    data = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line]
    assert data and data[0]["kind"] == "exec"


def test_run_handles_dry_run_and_timeout(monkeypatch):
    monkeypatch.setattr(executil, "_log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(executil, "trace", lambda *args, **kwargs: None)

    dry = executil.run(["echo", "hi"], dry_run=True)
    assert dry.out.startswith("DRY-RUN:")

    calls = {"count": 0}

    def fake_run(cmd, capture_output=True, text=True, timeout=None, env=None):
        if calls["count"] == 0:
            calls["count"] += 1
            raise executil.subprocess.TimeoutExpired(cmd, timeout)
        return SimpleNamespace(returncode=0, stdout="done", stderr="", args=cmd)

    monkeypatch.setattr(executil.subprocess, "run", fake_run)
    result = executil.run(["true"], check=True)
    assert result.out == "done"
    assert result.rc == 0


def test_run_raises_on_failure(monkeypatch):
    monkeypatch.setattr(executil, "_log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(executil, "trace", lambda *args, **kwargs: None)

    def fake_run(cmd, capture_output=True, text=True, timeout=None, env=None):
        return SimpleNamespace(returncode=1, stdout="bad", stderr="oops")

    monkeypatch.setattr(executil.subprocess, "run", fake_run)
    with pytest.raises(executil.subprocess.CalledProcessError):
        executil.run(["false"], check=True)


def test_with_backoff_eventually_succeeds(monkeypatch):
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("try again")
        return "ok"

    assert executil.with_backoff(flaky, tries=5, base=0.001, max_delay=0.001) == "ok"


    def always_fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        executil.with_backoff(always_fail, tries=2, base=0.0, max_delay=0.0)


def test_append_jsonl(tmp_path):
    path = tmp_path / "data" / "log.jsonl"
    executil.append_jsonl(str(path), {"foo": "bar"})
    text = path.read_text(encoding="utf-8").strip()
    assert json.loads(text) == {"foo": "bar"}


def test_udev_settle(monkeypatch):
    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)

    monkeypatch.setattr(executil.subprocess, "run", fake_run)
    executil.udev_settle()
    assert calls[0][0] == "udevadm"
