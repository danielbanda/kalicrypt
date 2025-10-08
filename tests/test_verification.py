import types

import pytest

from provision import verification


def test_helper_functions(monkeypatch):
    monkeypatch.setattr(verification, "_run", lambda cmd, check=False: {"rc": 1, "out": "", "err": ""})
    assert verification._command_output(["echo", "hi"]) == ""

    monkeypatch.setattr(verification, "_run", lambda cmd, check=False: {"rc": 0, "out": "value\n"})
    assert verification._command_output(["echo", "ok"]) == "value"

    monkeypatch.setattr(verification.os.path, "realpath", lambda path: (_ for _ in ()).throw(OSError()))
    assert verification._canon("/tmp/path") == "/tmp/path"

    def fake_open(*args, **kwargs):  # noqa: ANN001
        raise OSError("boom")

    monkeypatch.setattr("builtins.open", fake_open)
    assert "<read-failed" in verification._read("/missing")


def test_findmnt_source_failure(monkeypatch):
    monkeypatch.setattr(
        verification,
        "_run",
        lambda cmd, check=True: {"rc": 1, "out": "", "err": ""},
    )
    with pytest.raises(RuntimeError):
        verification._findmnt_source("/mnt")


class DummyProcess:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def test_run_adds_sudo_for_cryptsetup_when_not_root(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output=True, text=True):
        captured["cmd"] = cmd
        return DummyProcess(stdout="ok")

    monkeypatch.setattr(verification, "subprocess", types.SimpleNamespace(run=fake_run))
    monkeypatch.setattr(verification.os, "geteuid", lambda: 1000)

    result = verification._run(["cryptsetup", "luksUUID", "/dev/nvme0n1p3"])

    assert captured["cmd"][0] == "sudo"
    assert captured["cmd"][1:] == ["cryptsetup", "luksUUID", "/dev/nvme0n1p3"]
    assert result["cmd"] == captured["cmd"]


def test_run_does_not_add_sudo_when_root(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output=True, text=True):
        captured["cmd"] = cmd
        return DummyProcess(stdout="ok")

    monkeypatch.setattr(verification, "subprocess", types.SimpleNamespace(run=fake_run))
    monkeypatch.setattr(verification.os, "geteuid", lambda: 0)

    result = verification._run(["cryptsetup", "luksUUID", "/dev/nvme0n1p3"])

    assert captured["cmd"] == ["cryptsetup", "luksUUID", "/dev/nvme0n1p3"]
    assert result["cmd"] == captured["cmd"]


def test_verify_sources_success(monkeypatch):
    mapping = {
        "/mnt/nvme": "/dev/mapper/rp5vg-root",
        "/mnt/nvme/boot": "/dev/nvme0n1p2",
        "/mnt/nvme/boot/firmware": "/dev/nvme0n1p1",
    }

    monkeypatch.setattr(verification, "_findmnt_source", lambda mp: mapping[mp])
    monkeypatch.setattr(verification, "_canon", lambda path: path)

    result = verification.verify_sources(
        "/mnt/nvme",
        "/mnt/nvme/boot",
        "/mnt/nvme/boot/firmware",
        "/dev/mapper/rp5vg-root",
        "/dev/nvme0n1p2",
        "/dev/nvme0n1p1",
    )

    assert result["sources"]["root"]["matches"]
    assert result["sources"]["boot"]["matches"]
    assert result["sources"]["esp"]["matches"]


def test_verify_sources_mismatch(monkeypatch):
    mapping = {
        "/mnt/nvme": "/dev/mapper/rp5vg-root",
        "/mnt/nvme/boot": "/dev/nvme0n1p2",
        "/mnt/nvme/boot/firmware": "/dev/sdb1",
    }

    monkeypatch.setattr(verification, "_findmnt_source", lambda mp: mapping[mp])
    monkeypatch.setattr(verification, "_canon", lambda path: path)

    with pytest.raises(RuntimeError):
        verification.verify_sources(
            "/mnt/nvme",
            "/mnt/nvme/boot",
            "/mnt/nvme/boot/firmware",
            "/dev/mapper/rp5vg-root",
            "/dev/nvme0n1p2",
            "/dev/nvme0n1p1",
        )


def test_verify_fs_and_uuid_warns_on_uuid(monkeypatch):
    monkeypatch.setattr(verification, "_fstype_of", lambda dev: {"p1": "vfat", "p2": "ext4"}.get(dev, ""))

    uuid_map = {"p1": "UUID-A", "p2": "UUID-B", "p3": "UUID-C"}
    monkeypatch.setattr(verification, "_uuid_of", lambda dev: uuid_map[dev])

    result = verification.verify_fs_and_uuid(
        "p1",
        "p2",
        "p3",
        exp_uuid_p1="UUID-EXP-A",
        exp_uuid_p2="UUID-B",
        exp_uuid_luks="UUID-EXP-C",
    )

    assert "p1 uuid differs" in result["warnings"][0]
    assert "luks uuid differs" in result["warnings"][1]


def test_verify_fs_and_uuid_fstype_mismatch(monkeypatch):
    monkeypatch.setattr(verification, "_fstype_of", lambda dev: "ext4")

    with pytest.raises(RuntimeError):
        verification.verify_fs_and_uuid("p1", "p2", "p3")


def test_verify_triplet_success(tmp_path):
    esp_dir = tmp_path / "boot" / "firmware"
    esp_dir.mkdir(parents=True)
    etc_dir = tmp_path / "etc"
    etc_dir.mkdir()

    (esp_dir / "cmdline.txt").write_text("cryptdevice=UUID=abc123:cryptroot root=/dev/mapper/rp5vg-root rootwait")
    (etc_dir / "crypttab").write_text("cryptroot UUID=abc123 none\n")
    (etc_dir / "fstab").write_text("/dev/mapper/rp5vg-root / ext4 defaults 0 1\n")
    (esp_dir / "initramfs_2712").write_text("dummy")

    result = verification.verify_triplet(
        str(tmp_path),
        "boot/firmware",
        "rp5vg",
        "root",
        expected_luks_uuid="abc123",
    )

    assert result["warnings"] == []
    assert result["initramfs"]["matches"]


def test_verify_triplet_missing_cryptroot(tmp_path):
    esp_dir = tmp_path / "boot" / "firmware"
    esp_dir.mkdir(parents=True)
    etc_dir = tmp_path / "etc"
    etc_dir.mkdir()

    (esp_dir / "cmdline.txt").write_text("root=/dev/mapper/rp5vg-root")
    (etc_dir / "crypttab").write_text("# missing entry\n")
    (etc_dir / "fstab").write_text("/dev/mapper/rp5vg-root / ext4 defaults 0 1\n")
    (esp_dir / "initramfs_2712").write_text("dummy")

    with pytest.raises(RuntimeError):
        verification.verify_triplet(
            str(tmp_path),
            "boot/firmware",
            "rp5vg",
            "root",
        )


def test_nvme_boot_verification(monkeypatch, tmp_path):
    runs = []

    def fake_run(cmd, check=False):
        runs.append(cmd)
        if cmd[:2] == ["cryptsetup", "luksUUID"]:
            return {"rc": 0, "out": "abcd", "err": "", "cmd": cmd}
        return {"rc": 0, "out": "ok", "err": "", "cmd": cmd}

    monkeypatch.setattr(verification, "_run", fake_run)

    mnt_root = "/mnt/nvme"
    mapping = {
        f"{mnt_root}/boot/firmware/cmdline.txt": "cryptdevice=UUID=abcd:cryptroot root=/dev/mapper/rp5vg-root rootfstype=ext4 rootwait",
        f"{mnt_root}/etc/crypttab": "cryptroot UUID=abcd  none",
        f"{mnt_root}/etc/fstab": "/dev/mapper/rp5vg-root  /  ext4  defaults  0  1\n",
    }
    monkeypatch.setattr(verification, "_read", lambda path: mapping.get(path, ""))
    monkeypatch.setattr(verification.os.path, "exists", lambda path: True)
    monkeypatch.setattr(verification.os, "makedirs", lambda *args, **kwargs: None)

    result = verification.nvme_boot_verification(
        "/dev/nvme0n1",
        passphrase_file=str(tmp_path / "secret"),
        mnt_root=mnt_root,
        mnt_esp=str(tmp_path / "esp"),
    )

    assert result["ok"] is True
    assert any(step["name"] == "dryrun_open_mount" for step in result["steps"])
    assert any(cmd[0] == "cryptsetup" for cmd in runs)
