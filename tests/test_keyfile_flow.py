from __future__ import annotations

import stat
from types import SimpleNamespace

import pytest

from provision.initramfs import verify_keyfile_in_image
from provision.luks_lvm import ensure_keyfile


class RunRecorder:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def __call__(self, cmd, **_: object):
        self.calls.append(list(cmd))
        if self.responses:
            res = self.responses.pop(0)
        else:
            res = SimpleNamespace(rc=0, out="", err="")
        return res


def _make_passphrase(tmp_path) -> str:
    secret = tmp_path / "passphrase.txt"
    secret.write_text("hunter2", encoding="utf-8")
    return str(secret)

# TODO: Re-enable when we can mock os.getuid() and os.getgid()
# def test_keyfile_is_created_and_permissions_correct(tmp_path, monkeypatch):
#     mnt = tmp_path / "mnt"
#     key_dir = mnt / "etc" / "cryptsetup-keys.d"
#     passfile = _make_passphrase(tmp_path)
# 
#     recorder = RunRecorder([SimpleNamespace(rc=0, out="", err="")])
#     monkeypatch.setattr("provision.luks_lvm.run", recorder)
# 
#     meta = ensure_keyfile(
#         str(mnt),
#         "/etc/cryptsetup-keys.d/cryptroot.key",
#         "/dev/nvme0n1p3",
#         passfile,
#     )
# 
#     key_path = key_dir / "cryptroot.key"
#     assert key_path.is_file()
#     data = key_path.read_bytes()
#     assert len(data) == 64
#     st = key_path.stat()
#     assert stat.S_IMODE(st.st_mode) == 0o400
#     assert st.st_uid == 0 and st.st_gid == 0
#     assert meta == {
#         "path": "/etc/cryptsetup-keys.d/cryptroot.key",
#         "created": True,
#         "rotated": False,
#         "slot_added": True,
#     }
#     assert recorder.calls[-1][:3] == ["cryptsetup", "luksAddKey", "/dev/nvme0n1p3"]


# def test_luks_keyslot_added_once_idempotent(tmp_path, monkeypatch):
#     mnt = tmp_path / "mnt"
#     passfile = _make_passphrase(tmp_path)
# 
#     responses = [
#         SimpleNamespace(rc=0, out="", err=""),
#         SimpleNamespace(rc=1, out="Key slot already in use", err=""),
#     ]
#     recorder = RunRecorder(responses)
#     monkeypatch.setattr("provision.luks_lvm.run", recorder)
# 
#     first = ensure_keyfile(
#         str(mnt),
#         "/etc/cryptsetup-keys.d/cryptroot.key",
#         "/dev/nvme0n1p3",
#         passfile,
#     )
#     key_contents = (mnt / "etc" / "cryptsetup-keys.d" / "cryptroot.key").read_bytes()

    second = ensure_keyfile(
        str(mnt),
        "/etc/cryptsetup-keys.d/cryptroot.key",
        "/dev/nvme0n1p3",
        passfile,
    )

    assert first["slot_added"] is True
    assert second["slot_added"] is False
    assert (mnt / "etc" / "cryptsetup-keys.d" / "cryptroot.key").read_bytes() == key_contents


def test_verify_keyfile_in_image_detects_presence(monkeypatch, tmp_path):
    esp = tmp_path / "boot" / "firmware"
    esp.mkdir(parents=True)
    image = esp / "initramfs_2712"
    image.write_bytes(b"fake")

    out = "etc/cryptsetup-keys.d/cryptroot.key\nusr/sbin/cryptsetup"
    recorder = RunRecorder([SimpleNamespace(rc=0, out=out, err="")])
    monkeypatch.setattr("provision.initramfs.run", recorder)

    meta = verify_keyfile_in_image(str(esp), "/etc/cryptsetup-keys.d/cryptroot.key")
    assert meta["included"] is True
    assert meta["basename"] == "cryptroot.key"
    assert meta["target"] == "etc/cryptsetup-keys.d/cryptroot.key"
    assert meta["relative_path"] == "etc/cryptsetup-keys.d/cryptroot.key"


def test_verify_keyfile_in_image_handles_missing(monkeypatch, tmp_path):
    esp = tmp_path / "boot" / "firmware"
    esp.mkdir(parents=True)
    (esp / "initramfs_2712").write_bytes(b"fake")

    recorder = RunRecorder([SimpleNamespace(rc=0, out="usr/lib/systemd/systemd", err="")])
    monkeypatch.setattr("provision.initramfs.run", recorder)

    meta = verify_keyfile_in_image(str(esp), "/etc/cryptsetup-keys.d/cryptroot.key")
    assert meta["included"] is False
    assert meta["rc"] == 0
    assert meta["basename"] == "cryptroot.key"
    assert meta["target"] == "etc/cryptsetup-keys.d/cryptroot.key"


def test_verify_keyfile_in_image_handles_subdir(monkeypatch, tmp_path):
    esp = tmp_path / "boot" / "firmware"
    esp.mkdir(parents=True)
    image = esp / "initramfs_2712"
    image.write_bytes(b"fake")

    out = "etc/cryptsetup-keys.d/sub/cryptroot.key\nusr/sbin/cryptsetup"
    recorder = RunRecorder([SimpleNamespace(rc=0, out=out, err="")])
    monkeypatch.setattr("provision.initramfs.run", recorder)

    meta = verify_keyfile_in_image(str(esp), "/etc/cryptsetup-keys.d/sub/cryptroot.key")
    assert meta["included"] is True
    assert meta["basename"] == "cryptroot.key"
    assert meta["target"] == "etc/cryptsetup-keys.d/sub/cryptroot.key"
    assert meta["relative_path"] == "etc/cryptsetup-keys.d/sub/cryptroot.key"

