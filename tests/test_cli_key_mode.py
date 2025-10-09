from __future__ import annotations

from types import SimpleNamespace

import pytest

from provision import model
from provision.cli import _planned_steps, _require_keyfile_path, _normalize_keyfile_path, _plan_payload


def test_planned_steps_includes_keyfile_step_when_enabled():
    flags = model.Flags(keyfile_auto=True)
    steps = _planned_steps(flags)
    assert "install_keyfile()/luksAddKey()" in steps


def test_planned_steps_omits_keyfile_step_when_disabled():
    flags = model.Flags(keyfile_auto=False)
    steps = _planned_steps(flags)
    assert "install_keyfile()/luksAddKey()" not in steps


def test_plan_payload_carries_key_unlock(tmp_path, monkeypatch):
    plan = model.ProvisionPlan(device="/dev/nvme0n1")
    flags = model.Flags(keyfile_auto=True)
    fake_dm = model.DeviceMap(device="/dev/nvme0n1", p1="p1", p2="p2", p3="p3")
    fake_dm.root_lv_path = "/dev/mapper/rp5vg-root"

    monkeypatch.setattr("provision.cli.probe", lambda device, dry_run=True: fake_dm)
    monkeypatch.setattr(
        "provision.cli.run",
        lambda *args, **kwargs: SimpleNamespace(rc=0, out="", err="", duration=None),
    )
    monkeypatch.setattr("provision.cli._holders_snapshot", lambda device: "")
    payload = _plan_payload(plan, flags, root_src="/dev/root", safety_snapshot={})
    assert payload["key_unlock"] == {
        "mode": "keyfile",
        "path": "/etc/cryptsetup-keys.d/cryptroot.key",
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("/etc/cryptsetup-keys.d/key.bin", "/etc/cryptsetup-keys.d/key.bin"),
        ("etc/cryptsetup-keys.d/key.bin", "/etc/cryptsetup-keys.d/key.bin"),
    ],
)
def test_require_keyfile_path_accepts_valid(raw, expected):
    normalized = _normalize_keyfile_path(raw)
    assert _require_keyfile_path(normalized) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/boot/firmware/key.bin",
        "/etc/cryptsetup-keys.d",
        "../../etc/passwd",
    ],
)
def test_require_keyfile_path_rejects_outside_tree(path, monkeypatch):
    def fake_emit(*_args, **_kwargs):
        raise SystemExit()

    monkeypatch.setattr("provision.cli._emit_result", fake_emit)
    with pytest.raises(SystemExit):
        _require_keyfile_path(path)

