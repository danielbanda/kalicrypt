from types import SimpleNamespace

import pytest

from provision import initramfs


def test_ensure_packages_installs_missing(monkeypatch):
    calls = []

    def fake_run(cmd, check=False, dry_run=False, timeout=None):  # noqa: ARG001
        calls.append(list(cmd))
        if "dpkg" in cmd:
            return SimpleNamespace(rc=1)
        return SimpleNamespace(rc=0)

    monkeypatch.setattr(initramfs, "run", fake_run)
    stats = initramfs.ensure_packages("/mnt")
    assert any("apt-get" in " ".join(cmd) for cmd in calls)
    assert stats["retries"] == 0
    assert len(stats["installs"]) == len(initramfs.REQUIRED_PACKAGES)


def test_ensure_crypttab_prompts(tmp_path):
    ct = tmp_path / "etc" / "crypttab"
    ct.parent.mkdir()
    ct.write_text("cryptroot UUID=abcd /keyfile  luks\n", encoding="utf-8")
    initramfs._ensure_crypttab_prompts(str(tmp_path))
    assert "none" in ct.read_text(encoding="utf-8")


def test_detect_kernel_version(tmp_path):
    modules = tmp_path / "lib" / "modules"
    (modules / "6.1.0").mkdir(parents=True)
    (modules / "6.2.0").mkdir()
    assert initramfs._detect_kernel_version(str(tmp_path)) == "6.1.0"
    for child in modules.iterdir():
        if child.is_dir():
            for sub in child.iterdir():
                sub.unlink()
            child.rmdir()
    with pytest.raises(RuntimeError):
        initramfs._detect_kernel_version(str(tmp_path))


def test_rebuild_invokes_commands(monkeypatch):
    monkeypatch.setattr(initramfs, "_ensure_crypttab_prompts", lambda mnt: None)
    monkeypatch.setattr(initramfs, "_detect_kernel_version", lambda mnt: "6.1.0")
    calls = []

    def fake_run(cmd, check=False, dry_run=False, timeout=None):  # noqa: ARG001
        calls.append(list(cmd))
        if "-c" in cmd:
            return SimpleNamespace(rc=1)
        return SimpleNamespace(rc=0)

    monkeypatch.setattr(initramfs, "run", fake_run)
    meta = initramfs.rebuild("/mnt")
    assert any("update-initramfs" in " ".join(cmd) for cmd in calls)
    assert any(cmd[:3] == ["chroot", "/mnt", "/usr/bin/lsinitramfs"] for cmd in calls)
    assert meta["retries"] == 1


def test_verify_and_newest_initrd(tmp_path, monkeypatch):
    boot = tmp_path
    image = boot / "initramfs_999"
    image.write_bytes(b"0" * 200000)
    monkeypatch.setattr(initramfs, "verify_boot_surface", lambda path, luks_uuid=None: {"ok": True, "initramfs_path": str(image)})

    report = initramfs.verify(str(boot))
    assert report["ok"]
    assert report["initramfs_path"].endswith("initramfs_999")


def test_newest_initrd(tmp_path):
    (tmp_path / "initramfs_001").write_text("", encoding="utf-8")
    (tmp_path / "initramfs_010").write_text("", encoding="utf-8")
    assert initramfs.newest_initrd(str(tmp_path)).endswith("initramfs_010")
    for child in tmp_path.iterdir():
        child.unlink()
    with pytest.raises(RuntimeError):
        initramfs.newest_initrd(str(tmp_path))
