from __future__ import annotations

from types import SimpleNamespace

import pytest

from provision import model
import provision.cli as cli_module
from provision.cli import _plan_payload, _planned_steps, _require_keyfile_path, _normalize_keyfile_path


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


def test_normalize_keyfile_path_handles_none():
    assert _normalize_keyfile_path(None) is None


def _prime_main(monkeypatch):
    monkeypatch.setattr(cli_module, "_announce_log_path", lambda: "/tmp/ete-log.jsonl")
    monkeypatch.setattr(cli_module, "trace", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_module.os.path, "exists", lambda path: False)


@pytest.mark.parametrize(
    "flag",
    ["--keyfile-auto", "--keyfile-rotate", "--remove-passphrase"],
)
def test_main_requires_keyfile_path_for_keyfile_modes(monkeypatch, flag):
    _prime_main(monkeypatch)
    required: list[str] = []

    def fake_require(path: str) -> str:
        required.append(path)
        return path

    monkeypatch.setattr(cli_module, "_require_keyfile_path", fake_require)

    def fake_emit(*_args, **_kwargs):
        raise SystemExit

    monkeypatch.setattr(cli_module, "_emit_result", fake_emit)

    with pytest.raises(SystemExit):
        cli_module._main_impl(["/dev/fake", flag])

    assert required == ["/etc/cryptsetup-keys.d/cryptroot.key"]


def test_main_normalizes_keyfile_path_before_validation(monkeypatch):
    _prime_main(monkeypatch)
    recorded: list[str] = []

    def fake_require(path: str) -> str:
        recorded.append(path)
        return path

    monkeypatch.setattr(cli_module, "_require_keyfile_path", fake_require)

    def fake_emit(*_args, **_kwargs):
        raise SystemExit

    monkeypatch.setattr(cli_module, "_emit_result", fake_emit)

    with pytest.raises(SystemExit):
        cli_module._main_impl(
            [
                "/dev/fake",
                "--keyfile-rotate",
                "--keyfile-path",
                "/etc/cryptsetup-keys.d/./subdir/../custom.key",
            ]
        )

    assert recorded == ["/etc/cryptsetup-keys.d/custom.key"]


def test_main_skips_keyfile_validation_when_disabled(monkeypatch):
    _prime_main(monkeypatch)

    def unexpected_call(path: str) -> str:  # pragma: no cover - defensive guard
        raise AssertionError(f"_require_keyfile_path should not be called, received {path}")

    monkeypatch.setattr(cli_module, "_require_keyfile_path", unexpected_call)

    def fake_emit(*_args, **_kwargs):
        raise SystemExit

    monkeypatch.setattr(cli_module, "_emit_result", fake_emit)

    with pytest.raises(SystemExit):
        cli_module._main_impl(["/dev/fake"])

