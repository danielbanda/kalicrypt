from types import SimpleNamespace

from provision import luks_lvm


def test_format_and_open_luks(monkeypatch):
    calls = []

    def fake_run(cmd, check=False, dry_run=False, timeout=None):
        calls.append(cmd)
        if cmd[:2] == ["cryptsetup", "isLuks"]:
            return SimpleNamespace(rc=1)
        if cmd[:2] == ["sh", "-lc"]:
            return SimpleNamespace(out="no")
        return SimpleNamespace(rc=0, out="")

    monkeypatch.setattr(luks_lvm, "run", fake_run)
    monkeypatch.setattr(luks_lvm, "udev_settle", lambda: calls.append(["udev"]))

    luks_lvm.format_luks("/dev/p3", "/secret")
    luks_lvm.open_luks("/dev/p3", "cryptroot", "/secret")

    assert any(cmd[:2] == ["cryptsetup", "-q"] for cmd in calls)
    assert any(cmd[0] == "udev" for cmd in calls)


def test_make_and_manage_vg(monkeypatch):
    calls = []

    monkeypatch.setattr(luks_lvm, "run", lambda cmd, **kwargs: (calls.append(cmd), SimpleNamespace(rc=0))[1])
    monkeypatch.setattr(luks_lvm, "udev_settle", lambda: calls.append(["udev"]))

    luks_lvm.make_vg_lv("vg", "root")
    luks_lvm.activate_vg("vg")
    luks_lvm.deactivate_vg("vg")
    luks_lvm.close_luks("cryptroot")

    assert any(cmd[0] == "pvcreate" for cmd in calls)
    assert any(cmd[0] == "vgchange" and "-an" in cmd for cmd in calls)
    assert any(cmd == ["cryptsetup", "close", "cryptroot"] for cmd in calls)
