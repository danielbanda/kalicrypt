import subprocess

from provision import safety


def test_guard_not_live_disk_detects_overlap(monkeypatch):
    outputs = {
        ("findmnt", "-no", "SOURCE", "/"): "/dev/nvme0n1p2\n",
        ("findmnt", "-no", "SOURCE", "/boot"): "/dev/nvme0n1p1\n",
        ("lsblk", "-no", "PKNAME", "/dev/nvme0n1p2"): "nvme0n1\n",
        ("lsblk", "-no", "PKNAME", "/dev/nvme0n1p1"): "nvme0n1\n",
        ("lsblk", "-no", "PKNAME", "/dev/nvme0n1"): "nvme0n1\n",
    }

    def fake_check_output(cmd, text=True):
        key = tuple(part.strip() for part in cmd)
        return outputs.get(key, "")

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    ok, reason = safety.guard_not_live_disk("/dev/nvme0n1")
    assert not ok
    assert "live disk" in reason

    def safe_check_output(cmd, text=True):
        if cmd[-1] == "/dev/sda":
            return "sda\n"
        return "other\n"

    monkeypatch.setattr(subprocess, "check_output", safe_check_output)
    ok, reason = safety.guard_not_live_disk("/dev/sda")
    assert ok
