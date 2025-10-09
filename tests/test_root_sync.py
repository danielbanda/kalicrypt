import subprocess
from types import SimpleNamespace

from provision import root_sync


def test_parse_rsync_stats():
    text = """
Number of files transferred: 5
Total file size: 1.23G
Total transferred file size: 512M
Literal data: 10M
Matched data: 1.2G
File list size: 100K
Total bytes sent: 20M
Total bytes received: 5M
sent 100 bytes  received 200 bytes  300.00 bytes/sec
Speedup is 5.00
"""
    stats = root_sync.parse_rsync_stats(text)
    assert stats["files_transferred"] == 5
    assert stats["speedup"] == 5.0
    assert stats["total_file_size_bytes"] == 1_320_702_444
    assert stats["transferred_size_bytes"] == 536_870_912
    assert stats["throughput_bytes_per_sec"] == 300.0
    assert stats["bytes_sent_bytes"] == 20_971_520
    assert stats["bytes_received_bytes"] == 5_242_880


def test_rsync_root_with_rsync(monkeypatch):
    commands = []
    monkeypatch.setattr(root_sync.shutil, "which", lambda name: "/usr/bin/rsync")

    def fake_run(cmd, check=True, dry_run=False, timeout=None):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, out="", err="")

    monkeypatch.setattr(root_sync, "run", fake_run)
    result = root_sync.rsync_root("/mnt", dry_run=True, exclude_boot=True)
    assert isinstance(result, SimpleNamespace)
    assert commands[0][0].endswith("rsync")
    assert "--exclude" in commands[0]


def test_rsync_root_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(root_sync.shutil, "which", lambda name: None)

    def fake_run(cmd, check=True, dry_run=False, timeout=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(root_sync, "run", fake_run)
    root_sync.rsync_root("/mnt", dry_run=False, exclude_boot=True)
    assert calls[0][0] == "cp"
    assert any(cmd[0] == "rm" for cmd in calls[1:])


def test_rsync_root_partial_warning(monkeypatch):
    monkeypatch.setattr(root_sync.shutil, "which", lambda name: "/usr/bin/rsync")

    def fake_run(cmd, check=True, dry_run=False, timeout=None):
        raise subprocess.CalledProcessError(23, cmd, output="warning", stderr="err")

    monkeypatch.setattr(root_sync, "run", fake_run)
    res = root_sync.rsync_root("/mnt", dry_run=False)
    assert isinstance(res, subprocess.CalledProcessError)
    assert res.returncode == 23


def test_rsync_with_fallback(monkeypatch, tmp_path):
    calls = {"ran": False}

    class Proc:
        def __init__(self, rc):
            self.returncode = rc

    monkeypatch.setattr("subprocess.run", lambda cmd, capture_output=True, text=True: Proc(0))
    assert root_sync._rsync_with_fallback(root_sync.run, ["rsync"], "src", "dst") is True

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst"
    (src_dir / "file.txt").write_text("data", encoding="utf-8")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fail")))
    root_sync._rsync_with_fallback(root_sync.run, ["rsync"], str(src_dir), str(dst_dir))
    assert (dst_dir / "file.txt").read_text(encoding="utf-8") == "data"

    src_file = tmp_path / "single.txt"
    src_file.write_text("hello", encoding="utf-8")
    target = tmp_path / "copy" / "single.txt"
    root_sync._rsync_with_fallback(root_sync.run, ["rsync"], str(src_file), str(target))
    assert target.read_text(encoding="utf-8") == "hello"
