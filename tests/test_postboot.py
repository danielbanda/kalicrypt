import os
import stat

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
