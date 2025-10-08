from types import SimpleNamespace

import pytest

from provision import partitioning


def test_base_device_and_guard(monkeypatch):
    assert partitioning._base_device("/dev/nvme0n1p3") == "/dev/nvme0n1"

    monkeypatch.setattr(
        partitioning,
        "run",
        lambda cmd, check=False, dry_run=False: SimpleNamespace(out="/dev/nvme0n1p2\n"),
    )
    with pytest.raises(SystemExit):
        partitioning.guard_not_live_root("/dev/nvme0n1p1")


def test_precleanup_and_reread(monkeypatch):
    calls = []
    monkeypatch.setattr(partitioning, "run", lambda cmd, **kwargs: calls.append(cmd) or SimpleNamespace(out=""))
    monkeypatch.setattr(partitioning, "udev_settle", lambda: calls.append(["udev"]))

    partitioning.precleanup("/dev/nvme0n1")
    assert any(cmd[0] == "swapoff" for cmd in calls)

    calls.clear()
    partitioning.reread("/dev/nvme0n1")
    assert any(cmd[0] == "blockdev" for cmd in calls)


def test_create_helpers(monkeypatch):
    commands = []
    monkeypatch.setattr(partitioning, "run", lambda cmd, **kwargs: commands.append(cmd) or SimpleNamespace(out=""))
    monkeypatch.setattr(partitioning, "reread", lambda device, dry_run=False: commands.append(["reread", device]))
    monkeypatch.setattr(partitioning, "udev_settle", lambda: None)

    partitioning._create_with_sgdisk("/dev/nvme0n1", 256, 512, False)
    assert any(cmd[0] == "sgdisk" for cmd in commands)

    commands.clear()
    partitioning._create_with_parted("/dev/nvme0n1", 256, 512, False)
    assert any(cmd[0] == "parted" for cmd in commands)

    monkeypatch.setattr(partitioning, "run", lambda cmd, **kwargs: SimpleNamespace(out="\n 1  \n 2  \n 3 "))
    assert partitioning._have_three_parts("/dev/nvme0n1")


def test_apply_layout(monkeypatch):
    steps = []
    monkeypatch.setattr(partitioning, "guard_not_live_root", lambda device: steps.append("guard"))
    monkeypatch.setattr(partitioning, "precleanup", lambda device, dry_run=False: steps.append("precleanup"))
    monkeypatch.setattr(partitioning, "run", lambda cmd, **kwargs: steps.append(tuple(cmd)))
    monkeypatch.setattr(partitioning, "reread", lambda device, dry_run=False: steps.append("reread"))
    monkeypatch.setattr(partitioning, "_create_with_sgdisk", lambda *args, **kwargs: steps.append("sgdisk"))
    monkeypatch.setattr(partitioning, "_create_with_parted", lambda *args, **kwargs: steps.append("parted"))
    monkeypatch.setattr(partitioning, "_have_three_parts", lambda device, dry_run=False: True)

    partitioning.apply_layout("/dev/nvme0n1", 256, 512)
    assert "sgdisk" in steps

    monkeypatch.setattr(partitioning, "_have_three_parts", lambda device, dry_run=False: False)
    with pytest.raises(SystemExit):
        partitioning.apply_layout("/dev/nvme0n1", 256, 512)


def test_verify_layout(monkeypatch):
    called = []
    monkeypatch.setattr(partitioning, "run", lambda cmd, **kwargs: called.append(cmd))
    partitioning.verify_layout("/dev/nvme0n1")
    assert called and called[0][0] == "sgdisk"
