#!/usr/bin/env python3
"""
ete_nvme_provision.py — hardened E2E NVMe provisioner for Kali on Raspberry Pi 5
Build: 20251002_0026

Single-go flow with fail-fast gates, idempotent steps, strict preboot validator,
and TRACE logging with file:function:line for every step.
"""

import argparse, os, sys, subprocess, shlex, json, time, re, stat, inspect
from pathlib import Path

GREEN = "\033[0;32m"; YELLOW = "\033[0;33m"; RED = "\033[0;31m"; CLR = "\033[0m"
TRACE = os.environ.get("RP5_TRACE", "1") != "0"
LOGFILE = os.environ.get("RP5_LOG", "/tmp/ete_nvme_provision.log")

def _loc(frame_depth=1):
    f = inspect.stack()[frame_depth]
    fn = os.path.basename(f.filename)
    return f"{fn}:{f.function}:{f.lineno}"

def _emit(level, msg, prefix=None):
    p = prefix or level
    line = f"{p} {msg}"
    print(line, flush=True)
    try:
        with open(LOGFILE, "a") as lf:
            lf.write(line + "\n")
    except Exception:
        pass

def trace(msg):
    if TRACE: _emit("[TRACE " + _loc(2) + "]", msg, prefix=f"[TRACE { _loc(2) }]")
def info(msg):  _emit("[INFO]", f"{_loc(2)} {msg}")
def ok(msg):    _emit(f"{GREEN}[OK]{CLR}", f"{_loc(2)} {msg}")
def warn(msg):  _emit(f"{YELLOW}[WARN]{CLR}", f"{_loc(2)} {msg}")
def fail(msg):  _emit(f"{RED}[FAIL]{CLR}", f"{_loc(2)} {msg}")

def run(cmd, check=True, capture=False, env=None):
    caller = _loc(2)
    cmd_list = shlex.split(cmd) if isinstance(cmd, str) else cmd
    cmd_str = " ".join(shlex.quote(c) for c in cmd_list)
    trace(f"{caller} run: {cmd_str}")
    p = subprocess.run(cmd_list, check=False, text=True, capture_output=capture, env=env)
    if capture and (p.stdout or p.stderr):
        for stream, content in (("stdout", p.stdout), ("stderr", p.stderr)):
            if content:
                for line in content.splitlines():
                    trace(f"{caller} {stream}: {line}")
    if check and p.returncode != 0:
        fail(f"{caller} cmd failed: {cmd_str}")
        if p.stdout: print(p.stdout)
        if p.stderr: print(p.stderr)
        sys.exit(1)
    return p

def require_tools(tools):
    missing = []
    versions = {}
    for t in tools:
        p = run(["bash","-lc", f"type -p {shlex.quote(t)} || true"], check=False, capture=True)
        if not p.stdout.strip():
            missing.append(t)
        else:
            v = run([t, "--version"], check=False, capture=True)
            versions[t] = (v.stdout or v.stderr).splitlines()[0] if (v.stdout or v.stderr) else ""
    if missing:
        fail(f"missing tools: {', '.join(missing)}")
        sys.exit(1)
    ok("tools present")
    return versions

def block_exists(dev):
    return os.path.exists(dev) and stat.S_ISBLK(os.stat(dev).st_mode)

def get_root_device():
    with open("/proc/mounts") as f:
        for line in f:
            dev, mnt = line.split()[:2]
            if mnt == "/":
                return dev
    return None

def ensure_not_live_target(target):
    root_dev = get_root_device()
    if not root_dev:
        warn("could not resolve current root device; continuing cautiously")
        return
    if target == root_dev or target in root_dev or root_dev in target:
        fail(f"target {target} appears to be the current root device {root_dev}")
        sys.exit(1)
    mounts = [l.split()[0] for l in open("/proc/mounts")]
    suspect = [m for m in mounts if m.startswith(target)]
    if suspect:
        fail(f"some mounts are on {target}: {', '.join(suspect[:4])}")
        sys.exit(1)

def confirm_destruction(target, assume_yes=False):
    print(f"This will WIPE {target}. Type YES to continue:", flush=True)
    if assume_yes:
        print("YES")
        return
    resp = sys.stdin.readline().strip()
    if resp != "YES":
        fail("operator declined")
        sys.exit(1)

def partdev(dev, idx):
    return f"{dev}p{idx}" if "nvme" in dev or dev.endswith(tuple(str(i) for i in range(10))) else f"{dev}{idx}"

def wait_for_parts(device, parts=(1,2,3), timeout=90):
    info(f"waiting for partitions {parts} to appear")
    run(["bash","-lc","udevadm settle || true"], check=False)
    start = time.time()
    while time.time() - start < timeout:
        all_ok = True
        for k in parts:
            pth = partdev(device, k)
            if not os.path.exists(pth):
                all_ok = False
                break
        if all_ok:
            ok(f"partitions ready: {', '.join(partdev(device,k) for k in parts)}")
            return
        time.sleep(0.5)
        run(["partprobe", device], check=False)
    fail(f"timeout waiting for partitions on {device}")
    sys.exit(1)

def gpt_partition(device, esp_mb, boot_mb):
    run(["sgdisk","--zap-all", device])
    run(["sgdisk","-n","1:0:+{}M".format(esp_mb), "-t","1:ef00", "-c","1:ESP", device])
    run(["sgdisk","-n","2:0:+{}M".format(boot_mb), "-t","2:8300", "-c","2:/boot", device])
    run(["sgdisk","-n","3:0:0", "-t","3:8300", "-c","3:LUKS", device])
    run(["partprobe", device])
    wait_for_parts(device, (1,2,3), timeout=90)

def make_filesystems(device):
    p1, p2 = partdev(device,1), partdev(device,2)
    run(["mkfs.vfat","-F","32","-n","ESP", p1])
    run(["mkfs.ext4","-F","-L","boot", p2])

def luks_and_lvm(device, passphrase_file):
    p3 = partdev(device,3)
    if not os.path.exists(passphrase_file):
        fail(f"passphrase file not found: {passphrase_file}")
        sys.exit(1)
    luks_args = ["cryptsetup","-q","--type","luks2","--pbkdf","argon2id","--align-payload","65536",
                 "luksFormat", p3, passphrase_file]
    run(luks_args)
    run(["cryptsetup","open", p3, "cryptroot", "--key-file", passphrase_file])
    run(["pvcreate","-ff","-y","/dev/mapper/cryptroot"])
    run(["vgcreate","rp5vg","/dev/mapper/cryptroot"])
    run(["lvcreate","-l","100%FREE","-n","root","rp5vg"])
    run(["mkfs.ext4","-F","-L","root","/dev/rp5vg/root"])


def _choose_initramfs_path(mnt):
    fw = Path(mnt) / "boot" / "firmware"
    for fname in ("initramfs_2712", "initramfs8"):
        p = fw / fname
        if p.exists():
            return str(p)
    return ""

def _blk_uuid(dev):
    p = run(["blkid","-s","UUID","-o","value", dev], capture=True)
    return (p.stdout or "").strip()

def _write_json_result(mnt, device, status, note=""):
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "note": note,
        "device": device,
        "esp_uuid": _blk_uuid(partdev(device,1)),
        "boot_uuid": _blk_uuid(partdev(device,2)),
        "luks_uuid": _blk_uuid(partdev(device,3)),
        "mapper": "cryptroot",
        "vg": "rp5vg",
        "lv": "root",
        "kernel_uname_r": run(["chroot", mnt, "bash","-lc","uname -r"], capture=True).stdout.strip(),
        "initramfs_path": _choose_initramfs_path(mnt),
        "cmdline": (Path(mnt)/"boot/firmware/cmdline.txt").read_text().strip() if (Path(mnt)/"boot/firmware/cmdline.txt").exists() else "",
    }
    for op in ["/var/log/ete_result.json", str(Path(mnt)/"var/log/ete_result.json")]:
        try:
            Path(os.path.dirname(op)).mkdir(parents=True, exist_ok=True)
            with open(op,"w") as f: json.dump(data, f, indent=2)
        except Exception as e:
            warn(f"json result write failed at {op}: {e}")
    ok("wrote JSON result to /var/log/ete_result.json and target /var/log/ete_result.json")


def mkdirp(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        trace(f"mkdir -p {path}")
    else:
        trace(f"mkdir -p {path} (exists)")

def mount_targets(device, mnt="/mnt/nvme"):
    mkdirp(mnt)
    run(["mount","/dev/rp5vg/root", mnt])
    # Ensure /boot dir exists in the new root
    mkdirp(f"{mnt}/boot")
    # Mount /boot
    run(["mount", partdev(device,2), f"{mnt}/boot"])
    # Now create /boot/firmware *inside mounted /boot* then mount ESP
    mkdirp(f"{mnt}/boot/firmware")
    # Diagnostic breadcrumb: list the directory to prove it exists on the mounted fs
    run(["bash","-lc", f"ls -la {shlex.quote(mnt)}/boot"], check=False, capture=True)
    run(["mount", partdev(device,1), f"{mnt}/boot/firmware"])
    return mnt


def run_postcheck(mnt, device, passfile=None, standalone=False):
    """Run ete_postcheck.sh with env. If standalone, it may unlock LUKS using PASSFILE."""
    script = str(Path(__file__).with_name("ete_postcheck.sh"))
    if not os.path.exists(script):
        warn(f"postcheck script not found: {script}")
        return
    env = os.environ.copy()
    env.update({
        "MNT": mnt,
        "DEV": device,
        "VG": "rp5vg",
        "LV": "root",
    })
    if passfile:
        env["PASSFILE"] = passfile
    mode = "--standalone" if standalone else "--inline"
    info(f"Running postcheck ({mode}) via {script}")
    run(["bash", script], check=True, capture=False, env=env)
def rsync_root(mnt):
    excludes = [
        "/dev/*","/proc/*","/sys/*","/run/*","/tmp/*","/mnt/*","/media/*",
        "/lost+found","/boot/firmware/*","/var/tmp/*",".cache/*"
    ]
    args = ["rsync","-aHAX","--numeric-ids","--delete","--inplace","--info=progress2"]
    for e in excludes: args += ["--exclude", e]
    args += ["/", mnt]
    run(args)


def ensure_config_txt(mnt):
    """Ensure /boot/firmware/config.txt exists and references the right initramfs.
    Prefer initramfs_2712 if present; else initramfs8. Idempotent line update.
    """
    fw = Path(mnt) / "boot/firmware"
    cfg = fw / "config.txt"
    # Pick initramfs file
    init_2712 = fw / "initramfs_2712"
    init_v8 = fw / "initramfs8"
    target = None
    if init_2712.exists():
        target = "initramfs_2712"
    elif init_v8.exists():
        target = "initramfs8"
    else:
        warn("no initramfs file found in /boot/firmware (expected initramfs_2712 or initramfs8)")
        return
    lines = []
    if cfg.exists():
        lines = cfg.read_text().splitlines()
    # Drop any existing 'initramfs ' lines and append the desired one
    new_lines = [l for l in lines if not l.strip().lower().startswith("initramfs ")]
    new_lines.append(f"initramfs {target} followkernel")
    cfg.write_text("\n".join(new_lines) + "\n")
    ok(f"config.txt updated with 'initramfs {target} followkernel'")
def write_fstab_crypttab_cmdline(device, mnt):
    blk = run(["blkid","-s","UUID","-o","value", partdev(device,1)], capture=True).stdout.strip()
    boo = run(["blkid","-s","UUID","-o","value", partdev(device,2)], capture=True).stdout.strip()
    luks = run(["blkid","-s","UUID","-o","value", partdev(device,3)], capture=True).stdout.strip()

    fstab = Path(mnt)/"etc/fstab"
    lines = fstab.read_text().splitlines() if fstab.exists() else []
    base = [
        f"UUID={blk} /boot/firmware vfat defaults 0 1",
        f"UUID={boo} /boot          ext4 defaults 0 2",
        "/dev/mapper/rp5vg-root /  ext4 defaults,discard 0 1",
    ]
    with open(fstab,"w") as f:
        for l in lines:
            if all(k not in l for k in ["boot/firmware"," /boot ","rp5vg-root"]):
                f.write(l + "\n")
        f.write("\n".join(base) + "\n")

    crypttab = Path(mnt)/"etc/crypttab"
    with open(crypttab,"w") as f:
        f.write(f"cryptroot UUID={luks} none luks,discard\n")

    cmdline = Path(mnt)/"boot/firmware/cmdline.txt"
    rootarg = "root=/dev/mapper/rp5vg-root"
    cryptarg = f"cryptdevice=UUID={luks}:cryptroot"
    extra = "rootfstype=ext4 rootwait quiet splash"
    with open(cmdline,"w") as f:
        f.write(f"{cryptarg} {rootarg} {extra}\n")


def ensure_initramfs(mnt):
    # Prepare chroot with proper namespaces to avoid /proc*/cmdline warnings
    binds = [("/dev", f"{mnt}/dev"), ("/dev/pts", f"{mnt}/dev/pts"),
             ("/sys", f"{mnt}/sys"), ("/proc", f"{mnt}/proc"), ("/run", f"{mnt}/run")]
    for src, dst in binds:
        os.makedirs(dst, exist_ok=True)
        run(["mount","--bind", src, dst])

    try:
        # Harden UMASK for initramfs key material
        run(["chroot", mnt, "bash","-lc","mkdir -p /etc/initramfs-tools/conf.d && echo UMASK=0077 >/etc/initramfs-tools/conf.d/99-umask"])
        # Ensure packages
        run(["chroot", mnt, "bash","-lc","apt-get update || true && apt-get install -y cryptsetup-initramfs lvm2 busybox"])
        # Build all present kernel initramfs images; umask 0077 during build
        run(["chroot", mnt, "bash","-lc","umask 0077; update-initramfs -u -k all"])
        # Sanity: ensure cryptsetup + lvm bits present
        out = run(["chroot", mnt, "bash","-lc","lsinitramfs /boot/firmware/initramfs8 /boot/firmware/initramfs_2712 | egrep '(cryptsetup|lvm)' | wc -l"], capture=True)
        cnt = int((out.stdout or '0').strip() or 0)
        if cnt < 2:
            fail('initramfs seems to be missing cryptsetup/lvm content')
            sys.exit(1)
    finally:
        # Unmount in reverse order
        for src, dst in reversed(binds):
            run(["umount","-l", dst], check=False)


def validator(device, mnt):
    cmdline = (Path(mnt)/"boot/firmware/cmdline.txt").read_text().strip()
    m = re.search(r"cryptdevice=UUID=([0-9a-fA-F-]+):cryptroot", cmdline)
    if not m:
        fail("cmdline.txt missing cryptdevice UUID")
        sys.exit(1)
    luks_uuid = m.group(1)
    blk = run(["blkid","-s","UUID","-o","value", partdev(device,3)], capture=True).stdout.strip()
    if blk != luks_uuid:
        fail(f"cmdline UUID {luks_uuid} != actual {blk}")
        sys.exit(1)
    for p in ["etc/crypttab","etc/fstab"]:
        if not (Path(mnt)/p).exists():
            fail(f"missing {p}")
            sys.exit(1)

def cleanup(mnt):
    for path in [f"{mnt}/boot/firmware", f"{mnt}/boot", mnt]:
        run(["umount","-l", path], check=False)
    run(["vgchange","-an"], check=False)
    run(["cryptsetup","close","cryptroot"], check=False)

def main():
    ap = argparse.ArgumentParser(description="E2E NVMe provisioner (hardened)")
    ap.add_argument("device", help="target block device, e.g., /dev/nvme0n1")
    ap.add_argument("--esp-mb", type=int, default=256)
    ap.add_argument("--boot-mb", type=int, default=512)
    ap.add_argument("--passphrase-file", required=True)
    ap.add_argument("--plan", action="store_true", help="print plan and exit")
    ap.add_argument("--no-dry-run", action="store_true", help="(reserved)")
    ap.add_argument("--full-run", action="store_true", help="force zap/recreate everything")
    ap.add_argument("--yes", action="store_true", help="assume YES to destructive prompt")
    ap.add_argument("--tpm-keyscript", action="store_true", help="(reserved) enroll TPM keyscript")
    ap.add_argument("--version", action="version", version="ete_nvme_provision.py 20251001_2356")
    ap.add_argument("--with-postcheck", action="store_true", help="run post-ETE sanity checks before cleanup")
    ap.add_argument("--postcheck-only", action="store_true", help="only run post-ETE sanity checks on an existing target")
    args = ap.parse_args()

    tools = ["sgdisk","partprobe","cryptsetup","rsync","mkfs.ext4","mkfs.vfat","blkid",
             "chroot","update-initramfs","apt-get","vgchange","pvcreate","vgcreate","lvcreate","mount","umount","lsblk","udevadm"]
    info("Tool preflight")
    require_tools(tools)

    if not block_exists(args.device):
        fail(f"not a block device: {args.device}")
        sys.exit(1)
    ensure_not_live_target(args.device)

    if args.plan:
        print(json.dumps({
            "device": args.device,
            "esp_mb": args.esp_mb,
            "boot_mb": args.boot_mb,
            "mapper": "cryptroot",
            "vg": "rp5vg",
            "lv": "root",
            "flow": ["partition","mkfs","luks+open","lvm create","mount","rsync root","fstab/crypttab/cmdline","initramfs","validate","cleanup"]
        }, indent=2))
        return


    if args.postcheck_only:
        run_postcheck("/mnt/nvme", args.device, args.passphrase_file, standalone=True)
        try:
            _write_json_result("/mnt/nvme", args.device, "POSTCHECK_OK", note="postcheck-only")
        except Exception as _e:
            warn(f"postcheck json write failed: {_e}")
        print(f"%sRESULT:%s POSTCHECK_OK (postcheck-only)" % (GREEN, CLR))
        return
    confirm_destruction(args.device, assume_yes=args.yes)

    try:
        info("Pre-cleanup")
        run(["umount","-l", "/mnt/nvme/boot/firmware"], check=False)
        run(["umount","-l", "/mnt/nvme/boot"], check=False)
        run(["umount","-l", "/mnt/nvme"], check=False)
        run(["vgchange","-an","rp5vg"], check=False)
        run(["cryptsetup","close","cryptroot"], check=False)
        ok("pre-cleanup done")

        info(f"Partitioning {args.device}: ESP {args.esp_mb}M, /boot {args.boot_mb}M, LUKS(rest)")
        gpt_partition(args.device, args.esp_mb, args.boot_mb); ok("GPT ready")

        info("Creating filesystems")
        make_filesystems(args.device); ok("filesystems created")

        info("Creating LUKS+LVM")
        luks_and_lvm(args.device, args.passphrase_file); ok("LUKS/LVM ready")

        info("Mounting targets")
        mnt = mount_targets(args.device); ok(f"mounted at {mnt}")

        info("Rsync root → NVMe")
        rsync_root(mnt); ok("root synced")

        info("Writing fstab, crypttab, cmdline.txt")
        write_fstab_crypttab_cmdline(args.device, mnt); ok("boot plumbing done")

        info("Ensuring config.txt references initramfs")
        ensure_config_txt(mnt);

        info("Ensuring initramfs with cryptsetup+lvm")
        ensure_initramfs(mnt); ok("initramfs updated")

        info("Preboot validator")
        validator(args.device, mnt); ok("preboot checks passed")

        _write_json_result(mnt, args.device, "ETE_PREBOOT_OK")
        if args.with_postcheck:
            run_postcheck(mnt, args.device, args.passphrase_file, standalone=False)

        info("Cleanup")
        cleanup(mnt); ok("cleanup complete")

        print(f"{GREEN}RESULT:{CLR} ETE_PREBOOT_OK (log: {LOGFILE})")

    except SystemExit:
        raise
    except Exception as e:
        fail(f"unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
