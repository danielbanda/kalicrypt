import pytest

from provision import postcheck
from provision.verification import InitramfsVerificationError


def test_cleanup_pycache(tmp_path):
    root = tmp_path / "home" / "admin" / "rp5"
    cache_dir = root / "pkg" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "mod.cpython-311.pyc").write_text("", encoding="utf-8")
    (root / "file.pyc").write_text("", encoding="utf-8")

    stats = postcheck.cleanup_pycache(str(tmp_path))
    assert stats["removed_files"] >= 1


def test_run_postcheck_success(tmp_path, monkeypatch):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "crypttab").write_text("cryptroot UUID=abcd none\n", encoding="utf-8")
    (etc / "fstab").write_text("UUID=esp /boot/firmware vfat\n", encoding="utf-8")

    recovery_doc = tmp_path / "root" / "RP5_RECOVERY.md"
    recovery_doc.parent.mkdir(parents=True)
    recovery_doc.write_text("doc", encoding="utf-8")

    script = tmp_path / "usr" / "local" / "sbin" / "rp5-postboot-check"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh", encoding="utf-8")

    unit = tmp_path / "etc" / "systemd" / "system" / "rp5-postboot.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[Unit]", encoding="utf-8")

    boot_fw = tmp_path / "boot" / "firmware"
    boot_fw.mkdir(parents=True)
    (boot_fw / "cmdline.txt").write_text(
        "cryptdevice=UUID=abcd:cryptroot root=/dev/mapper/rp5vg-root\n",
        encoding="utf-8",
    )

    reported: dict[str, str] = {}

    def fake_verify(path, luks_uuid=None):  # noqa: ARG001
        reported["path"] = path
        reported["uuid"] = luks_uuid
        return {"ok": True, "initramfs_path": str(boot_fw / "initramfs_2712")}

    monkeypatch.setattr(postcheck, "verify_boot_surface", fake_verify)

    result = postcheck.run_postcheck(str(tmp_path), "abcd", p1_uuid="esp")
    assert result["ok"] is True
    assert any(check.get("fstab") for check in result["checks"])
    assert reported["path"] == str(boot_fw)
    assert reported["uuid"] == "abcd"
    assert result["installed"]["recovery_doc"]["host_path"] == str(recovery_doc)
    assert result["installed"]["heartbeat"]["exists"] is True

    with pytest.raises(RuntimeError):
        postcheck.run_postcheck(str(tmp_path / "missing"), "abcd")


def test_run_postcheck_initramfs_failure(tmp_path, monkeypatch):
    mnt = tmp_path
    etc = mnt / "etc"
    etc.mkdir()
    (etc / "crypttab").write_text("cryptroot UUID=abcd none\n", encoding="utf-8")
    (etc / "fstab").write_text("UUID=esp /boot/firmware vfat\n", encoding="utf-8")

    recovery_doc = mnt / "root" / "RP5_RECOVERY.md"
    recovery_doc.parent.mkdir(parents=True)
    recovery_doc.write_text("doc", encoding="utf-8")

    script = mnt / "usr" / "local" / "sbin" / "rp5-postboot-check"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh", encoding="utf-8")

    unit = mnt / "etc" / "systemd" / "system" / "rp5-postboot.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[Unit]", encoding="utf-8")

    boot_fw = mnt / "boot" / "firmware"
    boot_fw.mkdir(parents=True)

    # Ensure verify_boot_surface returns a failure surface
    failure_surface = {
        "ok": False,
        "checks": {
            "initramfs_2712": {
                "ok": False,
                "path": str(boot_fw / "initramfs_2712"),
                "size": 0,
                "why": "initramfs_2712 missing",
            }
        },
        "errors": [
            {
                "check": "initramfs_2712",
                "path": str(boot_fw / "initramfs_2712"),
                "why": "initramfs_2712 missing",
            }
        ],
    }

    monkeypatch.setattr(postcheck, "verify_boot_surface", lambda *a, **k: failure_surface)

    with pytest.raises(InitramfsVerificationError):
        postcheck.run_postcheck(str(mnt), "abcd")
