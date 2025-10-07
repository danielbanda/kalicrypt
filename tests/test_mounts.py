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


def test_mkfs_raises_mkfs_error(monkeypatch):
    calls: list[list[str]] = []

    class DummyResult:
        def __init__(self, rc: int = 0, out: str = "", err: str = "") -> None:
            self.rc = rc
            self.out = out
            self.err = err

    def fake_run(cmd, check=True, timeout=0.0, **_kwargs):  # noqa: ARG001 - signature matches executil.run
        calls.append(cmd)
        if cmd[0] == "wipefs":
            return DummyResult()
        if cmd[0] == "blkdiscard":
            return DummyResult()
        if cmd[0] == "mkfs.ext4":
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="boom")
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(
        mounts,
        "_collect_device_state",
        lambda dev: {
            "device": dev,
            "mountpoints": [],
            "holders": [],
            "read_only": False,
            "discard_capabilities": {"supports_discard": True},
        },
    )
    monkeypatch.setattr(mounts, "_device_discard_capabilities", lambda dev: {"supports_discard": True})
    monkeypatch.setattr(mounts, "_dmesg_tail", lambda lines=120: ["tail"])  # noqa: ARG005
    monkeypatch.setattr(mounts, "_lsblk_discard", lambda dev: "lsblk")
    monkeypatch.setattr(mounts, "_dmsetup_table_snapshot", lambda dev: {"rc": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(mounts, "udev_settle", lambda: None)
    monkeypatch.setattr(mounts.time, "sleep", lambda *_: None)

    with pytest.raises(mounts.MkfsError) as excinfo:
        mounts._mkfs("/dev/mapper/root", "ext4", label="root")

    assert "mkfs.ext4 failed on /dev/mapper/root: boom" in str(excinfo.value)
    assert excinfo.value.state["mkfs_attempts"]
    assert calls[0][:2] == ["wipefs", "-a"]
    assert excinfo.value.state["wipe"]["blkdiscard"]["rc"] == 0


def test_wipe_device_uses_dd_fallback(monkeypatch):
    commands: list[list[str]] = []

    class DummyResult:
        def __init__(self, rc: int = 0, out: str = "", err: str = "") -> None:
            self.rc = rc
            self.out = out
            self.err = err

    def fake_run(cmd, check=True, timeout=0.0, **_kwargs):  # noqa: ARG001
        commands.append(cmd)
        if cmd[0] == "wipefs":
            return DummyResult()
        if cmd[0] == "blkdiscard":
            return DummyResult(rc=1, err="unsupported")
        if cmd[0] == "dd":
            return DummyResult()
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(mounts, "run", fake_run)
    monkeypatch.setattr(mounts, "_collect_device_state", lambda dev: {"device": dev})
    monkeypatch.setattr(mounts, "_device_discard_capabilities", lambda dev: {"supports_discard": True})

    info = mounts._wipe_device("/dev/mapper/root")

    assert any(cmd[0] == "dd" for cmd in commands)
    assert info["dd_zero"]["rc"] == 0


def test_mkfs_preflight_blocks_busy_device(monkeypatch):
    run_mock = mock.Mock(side_effect=AssertionError("run should not be called when preflight fails"))
    monkeypatch.setattr(mounts, "run", run_mock)
    monkeypatch.setattr(
        mounts,
        "_collect_device_state",
        lambda dev: {
            "device": dev,
            "mountpoints": ["/mnt/inuse"],
            "holders": [],
            "read_only": False,
        },
    )

    with pytest.raises(mounts.MkfsError) as excinfo:
        mounts._mkfs("/dev/mapper/root", "ext4", label="root")

    assert "refusing to format" in str(excinfo.value)
    run_mock.assert_not_called()
