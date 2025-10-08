import json

from provision import recovery


def test_write_recovery_doc(tmp_path):
    meta = recovery.write_recovery_doc(str(tmp_path), "1234-ABCD")
    doc = tmp_path / "root/RP5_RECOVERY.md"
    assert "UUID=1234-ABCD" in doc.read_text(encoding="utf-8")
    assert meta["host_path"] == str(doc)
    assert meta["target_path"] == "/root/RP5_RECOVERY.md"
    assert meta["exists"] is True


def test_install_postboot_check_creates_script(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, check=False):
        calls.append((tuple(cmd), check))

    monkeypatch.setattr(recovery, "run", fake_run)

    recovery.install_postboot_check(str(tmp_path))

    script = tmp_path / "usr/local/sbin/rp5-postboot-check"
    assert script.exists()
    assert "cryptroot not active" in script.read_text(encoding="utf-8")
    assert calls == [(("chmod", "0755", str(script)), False)]


def test_bundle_artifacts_collects_present_logs(tmp_path, monkeypatch):
    added = []

    class DummyTar:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add(self, path, arcname=None):
            added.append((path, arcname))

    monkeypatch.setattr(recovery.tarfile, "open", lambda path, mode: DummyTar())

    present = {
        "/var/log/rp5/ete_nvme.jsonl": True,
        "/tmp/rp5-logs/ete_nvme.jsonl": False,
    }

    monkeypatch.setattr(recovery.os.path, "isfile", lambda p: present.get(p, False))

    def fake_makedirs(path, mode=0o777, exist_ok=False):
        return None

    monkeypatch.setattr(recovery.os, "makedirs", fake_makedirs)

    out_path = tmp_path / "bundle.tgz"

    recovery.bundle_artifacts(str(out_path), {"status": "ok"})

    assert added == [("/var/log/rp5/ete_nvme.jsonl", "ete_nvme.jsonl")]

    state = json.loads((tmp_path / "bundle.tgz.state.json").read_text(encoding="utf-8"))
    assert state == {"status": "ok"}
