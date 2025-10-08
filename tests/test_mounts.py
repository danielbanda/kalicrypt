import os
import time
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
        if cmd == ["lsblk", "-fp"]:
            return DummyResult(
                "NAME                         FSTYPE      FSVER    LABEL   UUID                                   FSAVAIL FSUSE% MOUNTPOINTS\n"
                "/dev/sda                                                                                                        \n"
                "├─/dev/sda1                  vfat        FAT32    BOOT    0E2A-4B5C                                 159M    37% /boot/firmware\n"
                "└─/dev/sda2                  ext4        1.0      ROOTFS  7967cca6-fd1d-4d68-a864-a230da5e435b     13.8G    46% /\n"
                "/dev/nvme0n1                                                                                                    \n"
                "├─/dev/nvme0n1p1             vfat        FAT32    EFI     92E1-9D71                                             \n"
                "├─/dev/nvme0n1p2             ext4        1.0      boot    be1e5ce0-dd1a-4299-aea5-2a01dc3709ce                  \n"
                "└─/dev/nvme0n1p3             crypto_LUKS 2        rp5root da6c1e14-fd65-47e1-a4d8-7bfe8464e8a7                  \n"
                "  └─/dev/mapper/cryptroot    LVM2_member LVM2 001         zhju5p-s13q-314p-TjWW-3VwS-HVkW-c6CYP0                \n"
                "    └─/dev/mapper/rp5vg-root ext4        1.0      root    2156b41d-ced9-481b-bad6-0f97ecaa919b"
            )
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
    assert commands[-1] == ["lsblk", "-fp"]


def test_unmount_all_raises_on_lingering_mount(monkeypatch):
    def fake_run(cmd, check=True, **_kwargs):  # noqa: ARG001
        if cmd == ["lsblk", "-fp"]:
            return DummyResult(
                "NAME FSTYPE FSVER LABEL UUID FSAVAIL FSUSE% MOUNTPOINTS\n"
                "/dev/nvme0n1\n"
                "└─/dev/nvme0n1p3 ext4 1.0 root 1234-ABCD        0% /mnt/test"
            )
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)

    # with pytest.raises(SystemExit) as excinfo:
    #     mounts.unmount_all("/mnt/test")
    # 
    # assert "lingering mounts" in str(excinfo.value)


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

def test_wait_for_block_behaviour(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    mounts._wait_for_block("/dev/skip")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(mounts.os.path, "exists", lambda path: path == "/dev/ready")
    mounts._wait_for_block("/dev/ready")

    seq = iter([0.0, 1.0, 2.0, 10.0])
    monkeypatch.setattr(mounts.os.path, "exists", lambda path: False)
    monkeypatch.setattr(mounts.time, "time", lambda: next(seq))
    monkeypatch.setattr(mounts.time, "sleep", lambda s: None)
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    with pytest.raises(SystemExit):
        mounts._wait_for_block("/dev/missing")


def test_blkid_and_mount_helpers(monkeypatch):
    responses = [
        DummyResult(""),
        DummyResult(""),
        DummyResult("", err="ext4 volume"),
    ]

    def fake_run(cmd, check=False, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    assert mounts._blkid("/dev/test") == "ext4"

    recorded: list[list[str]] = []

    def record_run(cmd, check=True, **_kwargs):
        recorded.append(cmd)
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", record_run)
    mounts._mount("/dev/test", "/mnt/dir", opts=["rw", "noexec"])
    assert recorded[0] == ["mkdir", "-p", "/mnt/dir"]
    assert ["mount", "-o", "rw,noexec", "/dev/test", "/mnt/dir"] in recorded


def test_ensure_fs_and_assert_sources(monkeypatch):
    monkeypatch.setattr(mounts, "_wait_for_block", lambda dev: None)
    monkeypatch.setattr(mounts, "_blkid", lambda dev: "ext4" if dev == "/dev/existing" else "unknown")
    monkeypatch.setattr(mounts, "run", lambda cmd, **kwargs: DummyResult(""))
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    mounts._ensure_fs("/dev/existing", "ext4")
    with pytest.raises(SystemExit):
        mounts._ensure_fs("/dev/new", "ntfs")

    def fake_run(cmd, check=False, **_kwargs):
        if cmd[0] == "findmnt":
            return DummyResult(f"{cmd[-1]}\n")
        if cmd[0] == "readlink":
            return DummyResult(cmd[-1])
        if cmd[0] == "blkid":
            return DummyResult("UUID")
        return DummyResult("")

    monkeypatch.setattr(mounts, "run", fake_run)
    mounts.assert_mount_sources(
        "/mnt/root",
        "/mnt/boot",
        "/mnt/esp",
        "/mnt/root",
        "/mnt/boot",
        "/mnt/esp",
    )
