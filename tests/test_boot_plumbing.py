import os

import pytest

from provision.boot_plumbing import (
    assert_cmdline_uuid,
    assert_crypttab_uuid,
    write_cmdline,
    write_crypttab,
    write_fstab,
    _resolve_root_mapper,
)


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def test_write_cmdline_overwrites_previous_content(tmp_path):
    esp = tmp_path / "boot" / "firmware"
    esp.mkdir(parents=True)
    cmdline_path = esp / "cmdline.txt"
    cmdline_path.write_text("root=PARTUUID=deadbeef\n", encoding="utf-8")

    write_cmdline(str(esp), "abcd-1234")

    txt = read(cmdline_path)
    expected = (
        "cryptdevice=UUID=abcd-1234:cryptroot "
        "root=/dev/mapper/rp5vg-root "
        "rootfstype=ext4 rootwait\n"
    )
    assert txt == expected

    # Running a second time should leave the same content in place.
    write_cmdline(str(esp), "abcd-1234")
    assert read(cmdline_path) == txt


def test_write_fstab_populates_expected_entries(tmp_path):
    root = tmp_path / "mnt"
    etc_dir = root / "etc"
    etc_dir.mkdir(parents=True)

    write_fstab(str(root), "uuid-esp", "uuid-boot")

    contents = read(etc_dir / "fstab")
    expected = (
        "UUID=uuid-esp  /boot/firmware  vfat  defaults,uid=0,gid=0,umask=0077  0  1\n"
        "UUID=uuid-boot  /boot  ext4  defaults  0  2\n"
        "/dev/mapper/rp5vg-root  /  ext4  defaults  0  1\n"
    )
    assert contents == expected
    assert contents.endswith("\n")


def test_write_crypttab_matches_template(tmp_path):
    root = tmp_path / "mnt"
    etc_dir = root / "etc"
    etc_dir.mkdir(parents=True)

    write_crypttab(str(root), "uuid-luks", "/home/admin/secret.txt")

    contents = read(etc_dir / "crypttab")
    assert contents == "cryptroot UUID=uuid-luks  /home/admin/secret.txt\n"

def test_resolve_root_mapper_defaults():
    assert _resolve_root_mapper(None, None, None) == "/dev/mapper/rp5vg-root"
    assert _resolve_root_mapper(" /custom ", None, None) == "/custom"


def test_assert_cmdline_uuid(tmp_path):
    esp = tmp_path / "boot" / "firmware"
    esp.mkdir(parents=True)
    path = esp / "cmdline.txt"
    path.write_text("cryptdevice=UUID=abcd:cryptroot root=/dev/mapper/cryptvg-root\n", encoding="utf-8")
    assert_cmdline_uuid(str(esp), "abcd", root_mapper="/dev/mapper/cryptvg-root")
    with pytest.raises(RuntimeError):
        assert_cmdline_uuid(str(esp), "xxxx")


def test_assert_crypttab_uuid(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    ct = etc / "crypttab"
    ct.write_text("cryptroot UUID=abcd none\n", encoding="utf-8")
    assert_crypttab_uuid(str(tmp_path), "abcd")
    ct.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError):
        assert_crypttab_uuid(str(tmp_path), "abcd")
