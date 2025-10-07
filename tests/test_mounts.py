from types import SimpleNamespace

import pytest

from provision import mounts


class DummyResult:
    def __init__(self, out: str = "", rc: int = 0, err: str = "") -> None:
        self.out = out
        self.rc = rc
        self.err = err


def test_mount_targets_formats_and_mounts(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(cmd, check=True, **_kwargs):  # noqa: ARG001 - signature compatibility
        commands.append(cmd)
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    monkeypatch.setattr(
        mounts,
        "_blkid",
        lambda dev: "ext4" if dev == "/dev/mapper/rp5vg-root" else "",
    )
    monkeypatch.setattr(
        mounts,
        "probe",
        lambda device, dry_run=False: SimpleNamespace(p1="/dev/p1", p2="/dev/p2"),
    )

    result = mounts.mount_targets("/dev/nvme0n1")

    assert result.mnt == "/mnt/nvme"
    assert result.boot == "/mnt/nvme/boot"
    assert result.esp == "/mnt/nvme/boot/firmware"

    assert ["mkfs.vfat", "-F", "32", "-n", "EFI", "/dev/p1"] in commands
    assert ["mkfs.ext4", "-F", "-L", "boot", "/dev/p2"] in commands
    assert ["mount", "/dev/mapper/rp5vg-root", "/mnt/nvme"] in commands
    assert ["mount", "/dev/p2", "/mnt/nvme/boot"] in commands
    assert ["mount", "-o", "umask=0077", "/dev/p1", "/mnt/nvme/boot/firmware"] in commands


def test_mount_targets_read_only_mode_guards(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(cmd, check=True, **_kwargs):  # noqa: ARG001 - signature compatibility
        commands.append(cmd)
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)

    def fake_blkid(dev):
        mapping = {
            "/dev/p1": "vfat",
            "/dev/p2": "ext4",
            "/dev/mapper/rp5vg-root": "ext4",
        }
        return mapping.get(dev, "")

    monkeypatch.setattr(mounts, "_blkid", fake_blkid)
    monkeypatch.setattr(
        mounts,
        "probe",
        lambda device, dry_run=False: SimpleNamespace(p1="/dev/p1", p2="/dev/p2", p3="/dev/p3"),
    )

    mounts.mount_targets("/dev/nvme0n1")

    mkfs_calls = [
        cmd for cmd in commands if cmd and cmd[0] in {"mkfs.vfat", "mkfs.ext4"}
    ]
    assert not mkfs_calls

    mount_calls = [cmd for cmd in commands if cmd and cmd[0] == "mount"]
    assert mount_calls


def test_bind_mounts_respects_dry_run(monkeypatch):
    calls: list[tuple[list[str], bool]] = []

    def fake_run(cmd, check=True, dry_run=False, **_kwargs):  # noqa: ARG001
        calls.append((cmd, dry_run))
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "trace", lambda *args, **kwargs: None)

    mounts.bind_mounts("/target", dry_run=True)

    mkdir_calls = [cmd for cmd, _ in calls if cmd and cmd[0] == "mkdir"]
    assert mkdir_calls
    assert all(dry_run for _cmd, dry_run in calls[: len(mkdir_calls)])

    bind_calls = [entry for entry in calls if entry[0][0] == "mount"]
    assert bind_calls
    assert all(entry[1] for entry in bind_calls)


def test_unmount_all_unmounts_expected_paths(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(cmd, check=True, **_kwargs):  # noqa: ARG001
        commands.append(cmd)
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)

    mounts.unmount_all("/mnt/test")

    assert commands[0] == ["sync"]
    assert ["umount", "-l", "/mnt/test/proc"] in commands
    assert ["umount", "-l", "/mnt/test/sys"] in commands
    assert ["umount", "-l", "/mnt/test/dev"] in commands
    assert ["umount", "-l", "/mnt/test/boot/firmware"] in commands
    assert ["umount", "-l", "/mnt/test/boot"] in commands
    assert ["umount", "-l", "/mnt/test"] in commands


def test_assert_mount_sources_detects_mismatch(monkeypatch):
    def fake_run(cmd, check=True, **_kwargs):  # noqa: ARG001
        if cmd[0] == "findmnt":
            mapping = {
                "/mnt/nvme": "/dev/mapper/actual-root\n",
                "/mnt/nvme/boot": "/dev/mapper/wrong-boot\n",
                "/mnt/nvme/boot/firmware": "/dev/mapper/actual-esp\n",
            }
            return DummyResult(mapping[cmd[-1]])
        if cmd[0] == "readlink":
            return DummyResult(cmd[-1])
        if cmd[0] == "blkid":
            return DummyResult("UUID-1234" if "wrong-boot" not in cmd[-1] else "UUID-mismatch")
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        mounts.assert_mount_sources(
            "/mnt/nvme",
            "/mnt/nvme/boot",
            "/mnt/nvme/boot/firmware",
            "/dev/mapper/expected-root",
            "/dev/mapper/expected-boot",
            "/dev/mapper/expected-esp",
        )

    assert "boot" in str(excinfo.value)


def test_mount_targets_safe_raises_on_failed_mount(monkeypatch):
    observed: list[list[str]] = []

    def fake_run(cmd, check=True, **_kwargs):  # noqa: ARG001
        observed.append(cmd)
        if cmd and cmd[0] == "mount" and "/dev/mapper/rp5vg-root" in cmd:
            return DummyResult("", rc=32, err="mount failed")
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    monkeypatch.setattr(
        mounts,
        "probe",
        lambda device, dry_run=False: SimpleNamespace(p1="/dev/p1", p2="/dev/p2", vg="rp5vg", lv="root"),
    )

    with pytest.raises(SystemExit) as excinfo:
        mounts.mount_targets_safe("/dev/nvme0n1")

    assert "mount failed" in str(excinfo.value)
    assert any(cmd for cmd in observed if cmd and cmd[0] == "mount")
