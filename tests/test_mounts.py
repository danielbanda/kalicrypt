import subprocess
from unittest import mock

import pytest

from provision import mounts


def test_await_block_device_retries_until_ready(monkeypatch):
    calls: list[str] = []

    def fake_is_block(path: str) -> bool:
        calls.append(path)
        return len(calls) >= 3

    monotonic_values = iter([0.0, 0.0, 0.1, 0.2])

    monkeypatch.setattr(mounts, "_is_block_device", fake_is_block)
    monkeypatch.setattr(mounts.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    monkeypatch.setattr(mounts.time, "sleep", lambda _: None)

    mounts._await_block_device("/dev/mapper/test", timeout=1.0)

    assert calls == ["/dev/mapper/test"] * 3


def test_await_block_device_missing(monkeypatch):
    monotonic_values = iter([0.0, 1.1])

    monkeypatch.setattr(mounts, "_is_block_device", lambda path: False)
    monkeypatch.setattr(mounts.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    monkeypatch.setattr(mounts.time, "sleep", lambda _: None)
    monkeypatch.setattr(mounts.os.path, "exists", lambda path: False)

    with pytest.raises(RuntimeError) as excinfo:
        mounts._await_block_device("/dev/mapper/miss", timeout=1.0)

    assert "did not appear" in str(excinfo.value)


def test_await_block_device_wrong_type(monkeypatch):
    monotonic_values = iter([0.0, 1.1])

    monkeypatch.setattr(mounts, "_is_block_device", lambda path: False)
    monkeypatch.setattr(mounts.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    monkeypatch.setattr(mounts.time, "sleep", lambda _: None)
    monkeypatch.setattr(mounts.os.path, "exists", lambda path: True)

    with pytest.raises(RuntimeError) as excinfo:
        mounts._await_block_device("/dev/mapper/notblk", timeout=1.0)

    assert "not a block device" in str(excinfo.value)


def test_mkfs_raises_runtime_error(monkeypatch):
    error = subprocess.CalledProcessError(1, ["mkfs.ext4"], output="", stderr="boom")
    run_mock = mock.Mock(side_effect=error)
    monkeypatch.setattr(mounts, "run", run_mock)

    with pytest.raises(RuntimeError) as excinfo:
        mounts._mkfs("/dev/mapper/root", "ext4", label="root")

    assert "mkfs.ext4 failed on /dev/mapper/root: boom" in str(excinfo.value)
    assert run_mock.call_args[0][0][0] == "mkfs.ext4"
