import os
import stat
from pathlib import Path

import pytest

from provision import postboot


@pytest.mark.parametrize("mnt_root", ["", "/"])
def test_install_postboot_check_ignores_empty_or_root(mnt_root):
    assert postboot.install_postboot_check(mnt_root) == {}


def test_write_file_handles_fsync_errors(tmp_path, monkeypatch):
    target = tmp_path / "heartbeat" / "check.sh"

    def failing_fsync(fd):
        raise OSError("boom")

    monkeypatch.setattr(postboot.os, "fsync", failing_fsync)

    postboot._write_file(target, "echo ok\n", 0o640)

    assert target.read_text(encoding="utf-8") == "echo ok\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_install_postboot_check_creates_assets(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, check=True):
        calls.append(("run", list(cmd), check))

    def fake_settle():
        calls.append(("udev",))

    monkeypatch.setattr(postboot, "run", fake_run)
    monkeypatch.setattr(postboot, "udev_settle", fake_settle)

    result = postboot.install_postboot_check(str(tmp_path))

    script = tmp_path / "usr/local/sbin/rp5-postboot-check"
    unit = tmp_path / "etc/systemd/system/rp5-postboot.service"
    wants_link = tmp_path / "etc/systemd/system/multi-user.target.wants/rp5-postboot.service"

    assert result == {"script": str(script), "unit": str(unit)}

    assert script.exists()
    assert "POSTBOOT_OK" in script.read_text(encoding="utf-8")
    assert os.access(script, os.X_OK)

    assert unit.exists()
    assert "ExecStart=/usr/local/sbin/rp5-postboot-check" in unit.read_text(encoding="utf-8")

    assert wants_link.parent.is_dir()

    assert calls[0] == (
        "run",
        ["ln", "-sf", "../rp5-postboot.service", str(wants_link)],
        True,
    )
    assert calls[1] == ("udev",)


@pytest.mark.parametrize("mnt_root", ["", "/"])
def test_remove_postboot_artifacts_ignores_empty_or_root(mnt_root):
    assert postboot.remove_postboot_artifacts(mnt_root) == {
        "artifacts": [],
        "skipped": True,
    }


def test_remove_postboot_artifacts_handles_missing(tmp_path):
    result = postboot.remove_postboot_artifacts(str(tmp_path))

    assert result["any_removed"] is False
    assert result["artifacts"]
    for entry in result["artifacts"]:
        assert entry["existed"] is False
        assert entry["removed"] is False


def test_remove_postboot_artifacts_removes_existing(tmp_path):
    artifacts = {
        Path("usr/local/sbin/rp5-postboot-check"),
        Path("etc/systemd/system/rp5-postboot.service"),
        Path("etc/systemd/system/multi-user.target.wants/rp5-postboot.service"),
        Path("root/RP5_RECOVERY.md"),
    }

    for rel in artifacts:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    result = postboot.remove_postboot_artifacts(str(tmp_path))

    assert result["any_removed"] is True

    for entry in result["artifacts"]:
        if entry["path"].startswith(str(tmp_path)):
            assert entry["existed"] is True
            assert entry["removed"] is True
            assert not Path(entry["path"]).exists()


def test_remove_postboot_artifacts_removes_directories(tmp_path, monkeypatch):
    target_dir = tmp_path / "usr/local/sbin/rp5-postboot-check"
    target_dir.mkdir(parents=True, exist_ok=True)

    file_targets = [
        tmp_path / "etc/systemd/system/rp5-postboot.service",
        tmp_path / "etc/systemd/system/multi-user.target.wants/rp5-postboot.service",
        tmp_path / "root/RP5_RECOVERY.md",
    ]
    for path in file_targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    calls = []
    real_rmtree = postboot.shutil.rmtree

    def recording_rmtree(path, ignore_errors=False):
        calls.append((path, ignore_errors))
        return real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(postboot.shutil, "rmtree", recording_rmtree)

    result = postboot.remove_postboot_artifacts(str(tmp_path))

    assert any(Path(entry["path"]) == target_dir for entry in result["artifacts"])
    assert any(call[0] == str(target_dir) for call in calls)
    assert not target_dir.exists()
