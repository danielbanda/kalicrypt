import json
from types import SimpleNamespace
from unittest import mock

from provision import devices


def test_probe_descends_nested_children(monkeypatch):
    payload = {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "children": [
                    {"name": "nvme0n1p1", "type": "part", "path": "/dev/nvme0n1p1"},
                    {"name": "nvme0n1p2", "type": "part", "path": "/dev/nvme0n1p2"},
                    {
                        "name": "nvme0n1p3",
                        "type": "part",
                        "path": "/dev/nvme0n1p3",
                        "children": [
                            {
                                "name": "cryptroot",
                                "type": "crypt",
                                "path": "/dev/mapper/cryptroot",
                                "children": [
                                    {
                                        "name": "cryptvg-root",
                                        "type": "lvm",
                                        "path": "/dev/mapper/cryptvg-root",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ]
    }

    run_mock = mock.Mock(return_value=SimpleNamespace(out=json.dumps(payload)))
    monkeypatch.setattr(devices, "run", run_mock)
    monkeypatch.setattr(devices, "udev_settle", lambda: None)

    result = devices.probe("/dev/nvme0n1")

    assert result.vg == "cryptvg"
    assert result.lv == "root"
    assert result.root_lv_path == "/dev/mapper/cryptvg-root"
