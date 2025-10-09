import json
import os
from types import SimpleNamespace

import pytest

from provision import cli


# def test_log_path_creates_directory(tmp_path, monkeypatch):
#     base = tmp_path / "logs"
#     monkeypatch.setattr(cli.os.path, "expanduser", lambda path: str(base) if path.startswith("~") else path)
#     path = cli._log_path("sample")
#     assert path.startswith(str(base))
#     assert base.is_dir()
#     assert os.path.basename(path).startswith("sample_")


def test_emit_result_records_and_exits(tmp_path, monkeypatch, capsys):
    records = []
    monkeypatch.setattr(cli, "append_jsonl", lambda path, payload: records.append((path, payload)))
    monkeypatch.setattr(cli.os.path, "expanduser", lambda p: str(tmp_path / "log.jsonl"))

    with pytest.raises(SystemExit) as exc:
        cli._emit_result("PLAN_OK", extra={"foo": "bar"})

    assert exc.value.code == cli.RESULT_CODES["PLAN_OK"]
    assert records and records[0][1]["result"] == "PLAN_OK"

    output = capsys.readouterr().out
    assert "PLAN_OK" in output


def test_write_json_artifact_writes_file(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    monkeypatch.setattr(cli, "_log_path", lambda name: str(target))

    payload = {"foo": "bar"}
    path = cli._write_json_artifact("test", payload)

    assert path == str(target)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["foo"] == "bar"
    assert saved["artifact"] == str(target)


def test_log_mounts_tolerates_failures(monkeypatch):
    calls = []

    def fake_run(cmd, check=False):
        calls.append(list(cmd))
        if len(calls) == 1:
            raise RuntimeError("fail once")
        return SimpleNamespace(out="")

    monkeypatch.setattr(cli, "run", fake_run)

    cli._log_mounts()
    # Should attempt all commands despite first failure
    assert len(calls) == 3


def test_record_result_returns_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "append_jsonl", lambda path, payload: None)
    monkeypatch.setattr(cli.os.path, "expanduser", lambda p: str(tmp_path / "log.jsonl"))

    payload = cli._record_result("OK", {"x": 1})
    assert payload["result"] == "OK"
    assert payload["x"] == 1


def test_plan_payload_collects_snapshot(monkeypatch):
    dm = SimpleNamespace(
        device="/dev/nvme0n1",
        p1="/dev/nvme0n1p1",
        p2="/dev/nvme0n1p2",
        p3="/dev/nvme0n1p3",
        vg="cryptvg",
        lv="root",
        root_lv_path="/dev/mapper/cryptvg-root",
    )
    monkeypatch.setattr(cli, "probe", lambda device, dry_run=False: dm)
    monkeypatch.setattr(cli, "_holders_snapshot", lambda device: "holder1\nholder2")
    monkeypatch.setattr(cli, "_same_underlying_disk", lambda device, root_src: False)

    def fake_run(cmd, check=False):
        return SimpleNamespace(out="HEADER\nline1\nline2")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli.time, "time", lambda: 1234567890)

    plan = cli.ProvisionPlan("/dev/nvme0n1", 256, 512, "/tmp/pass")
    flags = cli.Flags(plan=True, dry_run=False, skip_rsync=False, do_postcheck=False, tpm_keyscript=False, assume_yes=False)

    safety_snapshot = {
        "root_src": "/dev/root",
        "boot_src": "/boot",
        "target_device": plan.device,
        "target_pkname": "nvme0n",
    }

    payload = cli._plan_payload(plan, flags, "/dev/root", safety_snapshot)
    assert payload["plan"]["device"] == "/dev/nvme0n1"
    assert payload["state"]["holders"] == ["holder1", "holder2"]
    assert payload["steps"]
    assert payload["safety_check"] == safety_snapshot


def test_pre_sync_snapshot_aggregates(monkeypatch):
    outputs = {
        ("df", "-h"): "Filesystem",
        ("bash", "-lc", "mount | head -n 20"): "mount line",
    }

    def fake_run(cmd, check=False):
        key = tuple(cmd)
        text = outputs.get(key, "")
        return SimpleNamespace(out=text)

    monkeypatch.setattr(cli, "run", fake_run)

    class DummyFile:
        def __init__(self, text):
            self._text = text

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._text

    def fake_open(path, mode="r", encoding=None):
        if path == "/etc/hostname":
            return DummyFile("test-host\n")
        raise FileNotFoundError

    monkeypatch.setattr(cli, "open", fake_open, raising=False)

    snapshot = cli._pre_sync_snapshot()
    assert snapshot["df_h"] == ["Filesystem"]
    assert snapshot["mount_sample"] == ["mount line"]
    assert snapshot["hostname"] == "test-host"


def test_rsync_helpers():
    class Dummy:
        def __init__(self):
            self.returncode = 24
            self.output = "Number of files transferred: 5\n*deleting foo\nNumber of files transferred: 5\n"
            self.stderr = "warn"

    meta = cli._rsync_meta(Dummy())
    assert meta["warning"] is True
    summary = cli._rsync_summarize(meta["out"] or "Number of files transferred: 5\n")
    assert "counts" in summary


def test_normalize_and_require_passphrase(tmp_path, monkeypatch):
    called = {}

    def fake_emit(kind, extra=None, exit_code=None):
        called["kind"] = kind
        raise SystemExit(2)

    monkeypatch.setattr(cli, "_emit_result", fake_emit)
    monkeypatch.setattr(cli.os.path, "isfile", lambda path: False)

    with pytest.raises(SystemExit):
        cli._require_passphrase(None)

    secret_home = tmp_path / "home"
    secret_home.mkdir()
    monkeypatch.setattr(
        cli.os.path,
        "expanduser",
        lambda path: str(secret_home / os.path.basename(path)) if path.startswith("~") else path,
    )

    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(cli.os.path, "isfile", lambda path: path == str(secret))
    monkeypatch.setattr(cli.os.path, "getsize", lambda path: len(secret.read_text(encoding="utf-8")))

    monkeypatch.setattr(cli, "_emit_result", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not exit")))
    normalized = cli._normalize_passphrase_path("~/secret.txt")
    assert normalized.endswith("secret.txt")
    assert cli._require_passphrase(str(secret)).endswith("secret.txt")


def test_same_underlying_disk(monkeypatch):
    def fake_popen(cmd):
        value = "nvme0n1\n" if "target" in cmd else "nvme0n1\n"
        return SimpleNamespace(read=lambda: value)

    monkeypatch.setattr(cli.os, "popen", fake_popen)
    assert cli._same_underlying_disk("/dev/target", "/dev/root") is True

    def mismatched(cmd):
        if "target" in cmd:
            return SimpleNamespace(read=lambda: "nvme0n1\n")
        return SimpleNamespace(read=lambda: "sda\n")

    monkeypatch.setattr(cli.os, "popen", mismatched)
    assert cli._same_underlying_disk("/dev/target", "/dev/root") is False


def test_holders_snapshot(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout="output")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    result = cli._holders_snapshot("/dev/nvme0n1")
    assert "output" in result
    assert calls


def test_pre_cleanup_invokes_commands(monkeypatch):
    dm = SimpleNamespace(device="/dev/nvme0n1", p1="p1", p2="p2", p3="p3")
    monkeypatch.setattr(cli, "probe", lambda device: dm)

    invoked = []

    def fake_run(cmd, check=False):
        invoked.append(tuple(cmd))
        return SimpleNamespace(out="")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "udev_settle", lambda: None)
    monkeypatch.setattr(cli, "swapoff_all", lambda: None)
    monkeypatch.setattr(cli, "unmount_all", lambda path: None)
    monkeypatch.setattr(cli, "deactivate_vg", lambda vg: None)
    monkeypatch.setattr(cli, "close_luks", lambda name: None)

    cli.pre_cleanup("/dev/nvme0n1")
    assert any(cmd[0] == "wipefs" for cmd in invoked)


def test_build_parser_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["/dev/nvme0n1"])
    assert args.device == "/dev/nvme0n1"
    assert args.esp_mb == 256
    assert args.boot_mb == 512
