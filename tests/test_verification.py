import types

from provision import verification


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
