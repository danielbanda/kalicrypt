from provision.boot_plumbing import write_cmdline, write_fstab


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
    assert "cryptdevice=UUID=abcd-1234:cryptroot" in txt
    assert "root=/dev/mapper/rp5vg-root" in txt
    assert txt.endswith("\n")

    # Running a second time should leave the same content in place.
    write_cmdline(str(esp), "abcd-1234")
    assert read(cmdline_path) == txt


def test_write_fstab_populates_expected_entries(tmp_path):
    root = tmp_path / "mnt"
    etc_dir = root / "etc"
    etc_dir.mkdir(parents=True)

    write_fstab(str(root), "uuid-esp", "uuid-boot")

    contents = read(etc_dir / "fstab")
    assert "UUID=uuid-esp" in contents
    assert "UUID=uuid-boot" in contents
    assert "/dev/mapper/rp5vg-root" in contents
    assert contents.endswith("\n")
