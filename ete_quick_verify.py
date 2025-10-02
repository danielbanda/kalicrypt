#!/usr/bin/env python3
# RP5 ETE NVMe quick post-run verifier (belt & suspenders)
# - Idempotent: safe to re-run
# - Fail-fast: exits non-zero on failure
# - Optional rootfs checks if --passphrase-file is provided
#
# Usage:
#   sudo python3 ete_quick_verify.py --device /dev/nvme0n1 [--passphrase-file /root/secret.txt] [--mount-point /mnt/nvme-verify] [--force]
#
import argparse, os, shlex, subprocess, sys, json, time
from pathlib import Path

GREEN = "\033[32m"; RED = "\033[31m"; YEL = "\033[33m"; CLR = "\033[0m"

def run(cmd, check=True, capture=True):
    if isinstance(cmd, str):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd
    p = subprocess.run(cmd_list, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd_list}\n{p.stdout or ''}")
    return (p.stdout or "").strip()

def mounted(path):
    out = run(["findmnt", "-n", path], check=False)
    return bool(out)

def ensure_dir(p):
    Path(p).mkdir(parents=True, exist_ok=True)

def blk_uuid(dev):
    return run(["blkid", "-s", "UUID", "-o", "value", dev], check=False) or ""

def mount_dev(dev, mnt, fstype=None, opts=""):
    ensure_dir(mnt)
    if mounted(mnt):
        return True
    cmd = ["mount"]
    if fstype: cmd += ["-t", fstype]
    if opts:   cmd += ["-o", opts]
    cmd += [dev, mnt]
    return run(cmd, check=False) == ""

def umount_path(path, force=False):
    if not mounted(path):
        return True
    ok = True
    out = run(["umount", path], check=False)
    if mounted(path):
        if force:
            run(["fuser", "-km", path], check=False)
        run(["umount", "-l", path], check=False)
    if mounted(path):
        ok = False
    return ok

def open_luks(p3, mapping, passfile):
    # Non-interactive open using passphrase file
    if Path(f"/dev/mapper/{mapping}").exists():
        return True
    return run(["cryptsetup", "open", p3, mapping, f"--key-file={passfile}"], check=False) == ""

def close_luks(mapping):
    if Path(f"/dev/mapper/{mapping}").exists():
        run(["cryptsetup", "close", mapping], check=False)

def vg_activate(vg):
    run(["vgchange", "-ay", vg], check=False)

def vg_deactivate(vg):
    run(["vgchange", "-an", vg], check=False)

def read_text(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

def verify():
    ap = argparse.ArgumentParser(description="RP5 ETE NVMe post-run verifier")
    ap.add_argument("--device", default="/dev/nvme0n1")
    ap.add_argument("--passphrase-file", default=None)
    ap.add_argument("--mount-point", default="/mnt/nvme-verify")
    ap.add_argument("--force", action="store_true", help="forceful unmount if needed")
    args = ap.parse_args()

    dev = args.device
    p1, p2, p3 = f"{dev}p1", f"{dev}p2", f"{dev}p3"
    mnt = Path(args.mount_point)
    boot = mnt / "boot"
    esp = boot / "firmware"
    root_lv = "/dev/mapper/rp5vg-root"
    cryptmap = "cryptroot"

    ok = True
    checks = []

    def note(flag, msg):
        nonlocal ok
        checks.append({"ok": bool(flag), "msg": msg})
        print((f"{GREEN}[OK]{CLR}" if flag else f"{RED}[FAIL]{CLR}"), msg)
        if not flag:
            ok = False

    print(f"{YEL}==> Mounting /boot and ESP for inspection{CLR}")
    ensure_dir(boot); ensure_dir(esp)
    if not mount_dev(p2, str(boot)):
        note(False, f"mount {p2} -> {boot}"); 
    else:
        note(True,  f"mounted boot: {p2} -> {boot}")
    if not mount_dev(p1, str(esp)):
        note(False, f"mount {p1} -> {esp}")
    else:
        note(True,  f"mounted ESP:  {p1} -> {esp}")

    # 1) Firmware files exist
    for f in ["initramfs8", "initramfs_2712"]:
        path = esp / f
        note(path.exists(), f"ESP has {path}")

    # 2) config.txt content
    cfg = esp / "config.txt"
    cfg_txt = read_text(cfg)
    has_initramfs_line = ("initramfs" in cfg_txt.lower()) and ("followkernel" in cfg_txt.lower())
    note(cfg.exists(), f"{cfg} exists")
    note(has_initramfs_line, "config.txt includes 'initramfs ... followkernel'")

    # 3) cmdline.txt content
    cmdline = esp / "cmdline.txt"
    cmd = read_text(cmdline).strip()
    tokens = set(cmd.split())
    # cryptdevice UUID should match p3 UUID
    uuid_p3 = blk_uuid(p3)
    want_crypt = f"cryptdevice=UUID={uuid_p3}:cryptroot" if uuid_p3 else None
    want_root  = "root=/dev/mapper/rp5vg-root"
    for t in [want_root, "rootfstype=ext4", "rootwait"]:
        note(t in tokens, f"cmdline has '{t}'")
    if want_crypt:
        note(want_crypt in tokens, f"cmdline has '{want_crypt}'")
    else:
        note(any(x.startswith("cryptdevice=") for x in tokens), "cmdline has 'cryptdevice=...'")

    # 4) initramfs contents
    def lsir_has(path):
        out = run(["lsinitramfs", str(path)], check=False) or ""
        return any(x in out for x in ["cryptsetup", "dm-crypt", "lvm", "local-top/cryptroot"])
    has1 = lsir_has(esp / "initramfs8")
    has2 = lsir_has(esp / "initramfs_2712")
    note(has1, "initramfs8 contains cryptsetup/lvm bits")
    note(has2, "initramfs_2712 contains cryptsetup/lvm bits")

    # Optional rootfs checks
    did_open = False
    if args.passphrase_file and Path(args.passphrase_file).exists():
        print(f"{YEL}==> Optional rootfs checks (will open LUKS){CLR}")
        if open_luks(p3, cryptmap, args.passphrase_file):
            did_open = True
            vg_activate("rp5vg")
            # mount root read-only
            if not mounted(str(mnt)):
                mount_dev(root_lv, str(mnt), opts="ro")
            fstab = mnt / "etc/fstab"
            crypttab = mnt / "etc/crypttab"
            note(fstab.exists(), f"{fstab} exists")
            note(crypttab.exists(), f"{crypttab} exists")
            # simple expectations
            ft = read_text(fstab)
            ct = read_text(crypttab)
            note(" / " in ft or "/dev/mapper/rp5vg-root" in ft, "fstab declares root mapper")
            note("cryptroot" in ct, "crypttab declares 'cryptroot' mapping")
        else:
            note(False, "could not open LUKS for rootfs; skipping rootfs checks")

    # Cleanup
    print(f"{YEL}==> Cleanup (umount & deactivate){CLR}")
    umount_path(str(esp), force=args.force)
    umount_path(str(boot), force=args.force)
    if did_open:
        umount_path(str(mnt), force=args.force)
        vg_deactivate("rp5vg")
        close_luks(cryptmap)

    # Summarize
    status = "VERIFY_OK" if ok else "VERIFY_FAIL"
    print(f"{GREEN if ok else RED}RESULT: {status}{CLR}")
    # Write breadcrumb
    logdir = Path("/var/log"); ensure_dir(logdir)
    payload = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "device": dev, "status": status, "checks": checks}
    (logdir / "ete_verify.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(verify())
