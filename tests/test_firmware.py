import os
from pathlib import Path

import pytest

from provision import firmware


def test_populate_esp_uses_rsync(monkeypatch, tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "start4.elf").write_text("", encoding="utf-8")
    monkeypatch.setattr(firmware, "SRC_CANDIDATES", [str(src)])
    monkeypatch.setattr(firmware.os.path, "isdir", lambda p: p == str(src))
    monkeypatch.setattr(
        firmware.os.path,
        "isfile",
        lambda p: p == os.path.join(str(src), "start4.elf"),
    )
    monkeypatch.setattr(firmware.shutil, "which", lambda name: "/usr/bin/rsync")
    calls = []
    monkeypatch.setattr(firmware, "run", lambda cmd, check=True, dry_run=False: calls.append(cmd))

    firmware.populate_esp(str(dst))
    assert calls and calls[0][0] == "rsync"


def test_populate_esp_no_source(monkeypatch):
    monkeypatch.setattr(firmware, "SRC_CANDIDATES", ["/missing"])
    monkeypatch.setattr(firmware.os.path, "isdir", lambda p: False)
    with pytest.raises(RuntimeError):
        firmware.populate_esp("/dst")


def test_assert_essentials(tmp_path):
    (tmp_path / "start4.elf").write_bytes(b"0" * 2048)
    (tmp_path / "fixup4.dat").write_bytes(b"0" * 2048)
    (tmp_path / "bcm2712-test.dtb").write_text("", encoding="utf-8")
    (tmp_path / "overlays").mkdir()
    firmware.assert_essentials(str(tmp_path))
    (tmp_path / "start4.elf").unlink()
    with pytest.raises(RuntimeError):
        firmware.assert_essentials(str(tmp_path))

def test_populate_esp_fallback_to_cp(monkeypatch, tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "start4.elf").write_text("", encoding="utf-8")
    monkeypatch.setattr(firmware, "SRC_CANDIDATES", [str(src)])
    monkeypatch.setattr(firmware.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(
        firmware.os.path,
        "isfile",
        lambda p: p == os.path.join(str(src), "start4.elf"),
    )
    monkeypatch.setattr(firmware.shutil, "which", lambda name: None)
    captured = []
    monkeypatch.setattr(firmware, "run", lambda cmd, **kwargs: captured.append(cmd))

    firmware.populate_esp(str(dst))
    assert captured[0][:2] == ["cp", "-a"]
