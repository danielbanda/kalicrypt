from dataclasses import dataclass
from typing import Optional

@dataclass
class Flags:
    plan: bool = False
    dry_run: bool = False
    skip_rsync: bool = False
    do_postcheck: bool = False
    tpm_keyscript: bool = False
    assume_yes: bool = False

@dataclass
class ProvisionPlan:
    device: str
    esp_mb: int = 256
    boot_mb: int = 512
    passphrase_file: Optional[str] = None

@dataclass
class DeviceMap:
    device: str
    p1: str
    p2: str
    p3: str
    luks_name: str = "cryptroot"
    vg: str = "rp5vg"
    lv: str = "root"
    root_lv_path: str | None = None

@dataclass
class Mounts:
    mnt: str
    boot: str
    esp: str
