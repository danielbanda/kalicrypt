import stat

from provision import keyscript


def test_install_tpm_keyscript_writes_placeholder(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, check=False, dry_run=False):
        calls.append((tuple(cmd), check, dry_run))

    monkeypatch.setattr(keyscript, "run", fake_run)

    script_path = keyscript.install_tpm_keyscript(str(tmp_path), dry_run=True)

    dst = tmp_path / "lib/cryptsetup/scripts/cryptroot-tpm"
    assert script_path == keyscript.SCRIPT_PATH
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == keyscript.SCRIPT_CONTENT
    assert stat.S_IMODE(dst.stat().st_mode) == 0o755

    assert calls[0] == (("chroot", str(tmp_path), "/usr/bin/apt-get", "-y", "update"), False, True)
    assert calls[1] == (
        ("chroot", str(tmp_path), "/usr/bin/apt-get", "-y", "install", "tpm2-tools", "clevis", "clevis-initramfs"),
        False,
        True,
    )
