import json

from provision import preboot_check


def test_run_cmd(monkeypatch):
    monkeypatch.setattr(
        preboot_check.subprocess,
        "run",
        lambda cmd, shell=False, capture_output=True, text=True: type(
            "Proc", (), {"returncode": 0, "stdout": "out", "stderr": "err"}
        )(),
    )
    rc, out, err = preboot_check.run_cmd("echo test")
    assert rc == 0
    assert out == "out"


def test_preboot_check_main(monkeypatch, capsys):
    responses = [
        (0, "abcd", ""),
        (0, "cryptsetup\nlvm", ""),
        (0, "/rp5vg/root", ""),
    ]

    monkeypatch.setattr(preboot_check, "run_cmd", lambda cmd: responses.pop(0))
    mapping = {
        "/mnt/nvme/boot/firmware/cmdline.txt": "cryptdevice=UUID=abcd:cryptroot root=/dev/mapper/rp5vg-root",
        "/mnt/nvme/boot/firmware/config.txt": "initramfs initramfs_2712 followkernel",
        "/mnt/nvme/etc/fstab": "/dev/mapper/rp5vg-root",
        "/mnt/nvme/etc/crypttab": "cryptroot UUID=abcd none",
    }
    monkeypatch.setattr(preboot_check, "read", lambda path: mapping.get(path, ""))

    code = preboot_check.main()
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["checks"]["cmdline_exists"] is True
