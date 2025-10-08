import os

import pytest

from provision import postcheck


def test_cleanup_pycache(tmp_path):
    root = tmp_path / "home" / "admin" / "rp5"
    cache_dir = root / "pkg" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "mod.cpython-311.pyc").write_text("", encoding="utf-8")
    (root / "file.pyc").write_text("", encoding="utf-8")

    stats = postcheck.cleanup_pycache(str(tmp_path))
    assert stats["removed_files"] >= 1


def test_run_postcheck_success(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "crypttab").write_text("cryptroot UUID=abcd none\n", encoding="utf-8")
    (etc / "fstab").write_text("UUID=esp /boot/firmware vfat\n", encoding="utf-8")

    boot_fw = tmp_path / "boot" / "firmware"
    boot_fw.mkdir(parents=True)
    (boot_fw / "cmdline.txt").write_text(
        "cryptdevice=UUID=abcd:cryptroot root=/dev/mapper/rp5vg-root\n",
        encoding="utf-8",
    )

    (tmp_path / "initrd.img").write_text("", encoding="utf-8")
    (tmp_path / "vmlinuz").write_text("", encoding="utf-8")

    result = postcheck.run_postcheck(str(tmp_path), "abcd", p1_uuid="esp")
    assert result["ok"] is True
    assert any(check.get("fstab") for check in result["checks"])

    with pytest.raises(RuntimeError):
        postcheck.run_postcheck(str(tmp_path / "missing"), "abcd")
