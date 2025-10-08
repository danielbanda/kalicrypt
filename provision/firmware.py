"""Populate ESP with Raspberry Pi firmware & assert essentials (Phase 2)."""
import glob
import os
import shutil

from .executil import run

SRC_CANDIDATES = ["/boot/firmware", "/usr/lib/raspberrypi/boot"]


def populate_esp(dst_boot_fw: str, preserve_cmdline=True, preserve_config=True, dry_run: bool = False):
    src = next((c for c in SRC_CANDIDATES if os.path.isdir(c) and os.path.isfile(os.path.join(c, "start4.elf"))), None)
    if not src:
        raise RuntimeError("populate_esp: no firmware source found (looked in: %s)" % ", ".join(SRC_CANDIDATES))
    excludes = []
    if preserve_cmdline: excludes += ["--exclude", "cmdline.txt"]
    if preserve_config:  excludes += ["--exclude", "config.txt"]
    if shutil.which("rsync"):
        run(["rsync", "-aHAX"] + excludes + [src + "/", dst_boot_fw + "/"], check=True, dry_run=dry_run)
    else:
        run(["cp", "-a", src + "/.", dst_boot_fw], check=True, dry_run=dry_run)


def assert_essentials(dst_boot_fw: str):
    need_files = ["start4.elf", "fixup4.dat"]
    for f in need_files:
        if not os.path.isfile(os.path.join(dst_boot_fw, f)) or os.path.getsize(os.path.join(dst_boot_fw, f)) < 1024:
            raise RuntimeError(f"firmware: missing or tiny {f}")
    if not glob.glob(os.path.join(dst_boot_fw, "bcm2712*.dtb")):
        raise RuntimeError("firmware: bcm2712*.dtb not found")
    if not os.path.isdir(os.path.join(dst_boot_fw, "overlays")):
        raise RuntimeError("firmware: overlays/ missing")
