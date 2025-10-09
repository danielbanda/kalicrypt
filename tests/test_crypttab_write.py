from __future__ import annotations

import pytest

from provision.boot_plumbing import write_crypttab


def test_write_crypttab_prefers_keyfile_when_enabled(tmp_path):
    root = tmp_path / "mnt"
    ct_path = root / "etc" / "crypttab"
    ct_path.parent.mkdir(parents=True)

    write_crypttab(
        str(root),
        "uuid-luks",
        None,
        keyfile_path="/etc/cryptsetup-keys.d/cryptroot.key",
        enable_keyfile=True,
    )

    contents = ct_path.read_text(encoding="utf-8")
    assert (
            contents
            == "cryptroot UUID=uuid-luks  /etc/cryptsetup-keys.d/cryptroot.key  luks,discard\n"
    )


def test_write_crypttab_keeps_prompt_when_disabled(tmp_path):
    root = tmp_path / "mnt"
    ct_path = root / "etc" / "crypttab"
    ct_path.parent.mkdir(parents=True)

    write_crypttab(str(root), "uuid-luks", None)

    contents = ct_path.read_text(encoding="utf-8")
    assert contents == "cryptroot UUID=uuid-luks  none  luks\n"


def test_write_crypttab_respects_custom_path(tmp_path):
    root = tmp_path / "mnt"
    ct_path = root / "etc" / "crypttab"
    ct_path.parent.mkdir(parents=True)

    custom = "/etc/cryptsetup-keys.d/custom.key"
    write_crypttab(
        str(root),
        "uuid-luks",
        None,
        keyfile_path=custom,
        enable_keyfile=True,
    )

    assert ct_path.read_text(encoding="utf-8") == (
        "cryptroot UUID=uuid-luks  /etc/cryptsetup-keys.d/custom.key  luks,discard\n"
    )


def test_write_crypttab_rejects_invalid_key_path(tmp_path):
    root = tmp_path / "mnt"
    ct_path = root / "etc" / "crypttab"
    ct_path.parent.mkdir(parents=True)
    ct_path.write_text("cryptroot UUID=uuid none  luks\n", encoding="utf-8")

    with pytest.raises(ValueError):
        write_crypttab(
            str(root),
            "uuid",
            None,
            keyfile_path="/boot/firmware/key.bin",
            enable_keyfile=True,
        )

    # File should remain unchanged
    assert ct_path.read_text(encoding="utf-8") == "cryptroot UUID=uuid none  luks\n"


@pytest.mark.parametrize("enable", [False, True])
def test_write_crypttab_idempotent(tmp_path, enable):
    root = tmp_path / "mnt"
    ct_path = root / "etc" / "crypttab"
    ct_path.parent.mkdir(parents=True)

    kwargs = {
        "keyfile_path": "/etc/cryptsetup-keys.d/cryptroot.key",
        "enable_keyfile": enable,
    }
    write_crypttab(str(root), "uuid-luks", None, **kwargs)
    first = ct_path.read_text(encoding="utf-8")

    write_crypttab(str(root), "uuid-luks", None, **kwargs)
    second = ct_path.read_text(encoding="utf-8")

    assert first == second
