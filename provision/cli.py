"""CLI entrypoint for RP5 NVMe Provisioner (Phase 6)."""
import argparse, os, sys, json, time, subprocess, re
from .executil import trace
from .executil import append_jsonl
import os
from . import safety

RESULT_CODES = {
 'PLAN_OK':0,'DRYRUN_OK':0,'ETE_PREBOOT_OK':0,'ETE_DONE_OK':0,
 'FAIL_SAFETY_GUARD':2,'FAIL_MISSING_PASSPHRASE':2,'FAIL_FIRMWARE_CHECK':3,
 'FAIL_PARTITIONING':4,'FAIL_LUKS':5,'FAIL_LVM':6,'FAIL_RSYNC':7,'FAIL_POSTCHECK':8,'FAIL_GENERIC':9
,
    'FAIL_RSYNC_SKIPPED_FULLRUN': 10
,
    'FAIL_INITRAMFS_VERIFY': 11
,
    'FAIL_UNHANDLED': 12
,
    'FAIL_INVALID_DEVICE': 13
,
    'POSTCHECK_OK': 14
}


def _log_path(name:str)->str:
    base = os.path.expanduser("~/rp5/03_LOGS")
    try: os.makedirs(base, exist_ok=True)
    except Exception: pass
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(base, f"{name}_{ts}.json")

def _emit_result(kind:str, extra:dict|None=None, exit_code:int|None=None):
    payload = {"result": kind, "ts": int(time.time())}
    if extra: payload.update(extra)
    append_jsonl(os.path.expanduser("~/rp5/03_LOGS/ete_nvme.jsonl"), payload)
    print(json.dumps(payload, indent=2))
    code = RESULT_CODES.get(kind, 1) if exit_code is None else exit_code
    raise SystemExit(code)

def _write_json_artifact(name:str, data:dict):
    path = _log_path(name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return path

from .devices import probe, swapoff_all, holders, kill_holders, uuid_of
from .model import Flags, ProvisionPlan, DeviceMap, Mounts
from .partitioning import apply_layout, verify_layout
from .luks_lvm import format_luks, open_luks, make_vg_lv, deactivate_vg, close_luks
from .mounts import mount_targets, bind_mounts, unmount_all, assert_mount_sources
from .root_sync import rsync_root
from .firmware import populate_esp, assert_essentials
from .postcheck import run_postcheck, cleanup_pycache
from .boot_plumbing import write_fstab, write_crypttab, write_cmdline, assert_cmdline_uuid
from .initramfs import ensure_packages, rebuild, verify as verify_initramfs
from .recovery import write_recovery_doc, install_postboot_check, bundle_artifacts
from .postcheck import run_postcheck, cleanup_pycache
from .boot_plumbing import assert_crypttab_uuid, assert_cmdline_uuid

def _log_mounts():
    try:
        r = run(["findmnt","-R","/mnt/nvme"], check=False, read_only=False)
        if getattr(r, "out", None):
            print("[DIAG] findmnt -R /mnt/nvme:")
            print(r.out)
    except Exception:
        pass
    try:
        r = run(["lsblk","-f"], check=False, read_only=False)
        if getattr(r, "out", None):
            print("[DIAG] lsblk -f:")
            print(r.out)
    except Exception:
        pass
    try:
        r = run(["mount"], check=False, read_only=False)
        if getattr(r, "out", None):
            print("[DIAG] mount lines for /mnt/nvme and /mapper:")
            print("\n".join([ln for ln in r.out.splitlines() if "/mnt/nvme" in ln or "/mapper" in ln]))
    except Exception:
        pass


def _rsync_meta(res):
    meta = {"exit": None, "out": None, "err": None, "warning": None}
    try:
        if hasattr(res, "returncode"):
            meta["exit"] = res.returncode
        if hasattr(res, "output") and res.output:
            meta["out"] = res.output if isinstance(res.output, str) else res.output.decode(errors="ignore")
        if hasattr(res, "stderr") and res.stderr:
            meta["err"] = res.stderr if isinstance(res.stderr, str) else res.stderr.decode(errors="ignore")
        if hasattr(res, "code") and meta["exit"] is None:
            meta["exit"] = res.code
        if hasattr(res, "out") and meta["out"] is None:
            meta["out"] = res.out
        if hasattr(res, "err") and meta["err"] is None:
            meta["err"] = res.err
    except Exception:
        pass
    if meta["exit"] is None:
        meta["exit"] = 0
    if meta["exit"] in (23, 24):
        meta["warning"] = "partial transfer (vanished or permission-restricted files)"
    return meta
def _rsync_summarize(out_text: str, max_items: int = 30):
    if not out_text:
        return {"itemized_sample": [], "counts": {}, "stats": {}, "deleted": [], "numbers": [], "numbers_block": []}
    lines = [l for l in out_text.splitlines()]
    # Itemized changes (first page sample)
    itemized = [l for l in lines if l and (l[0] in {">","*","."} or l.startswith("deleting") or l.startswith("*deleting"))]
    sample = [l for l in itemized if l.strip()][:max_items]
    # Collect all "Number of ..." lines
    numbers = [l for l in lines if l.startswith("Number of ")]
    # Build a numbers_block from the first "Number of ..." to the end
    idx = next((i for i,l in enumerate(lines) if l.startswith("Number of ")), None)
    numbers_block = lines[idx:] if idx is not None else []
    # Simple counters
    counts = {
        "created": sum(1 for l in itemized if "f+++++++++" in l),
        "changed": sum(1 for l in itemized if ">f" in l or ".d..t" in l or "f..t" in l or "f.st" in l),
        "deleted": sum(1 for l in itemized if "deleting" in l)}
    stats = {}
    tail = [l for l in lines[-80:]]
    for l in tail:
        if l.startswith("Total transferred file size:"):
            stats["transferred"] = l.split(":",1)[1].strip()
        elif l.startswith("Total file size:"):
            stats["total"] = l.split(":",1)[1].strip()
        elif l.startswith("File list size:"):
            stats["file_list"] = l.split(":",1)[1].strip()
        elif l.startswith("sent ") and " bytes  received " in l:
            stats["throughput"] = l.strip()
    deleted = [l.split(None,1)[1] for l in itemized if l.startswith("*deleting")] [:max_items]
    return {"itemized_sample": sample, "counts": counts, "stats": stats, "deleted": deleted, "numbers": [n for n in numbers], "numbers_block": [n for n in numbers_block if n.strip()]}
    lines = [l for l in out_text.splitlines() if l.strip()]
    # Itemized changes (first page sample)
    itemized = [l for l in lines if l[:1] in {">","*","."} or l.startswith("deleting") or l.startswith("*deleting")]
    sample = itemized[:max_items]
    # Parse key Number* lines (rsync --stats footer)
    numbers = [l for l in lines if l.startswith("Number of ")]
    counts = {
        "created": sum(1 for l in itemized if "f+++++++++" in l),
        "changed": sum(1 for l in itemized if ">f" in l or ".d..t" in l or "f..t" in l or "f.st" in l),
        "deleted": sum(1 for l in itemized if "deleting" in l)}
    stats = {}
    for l in reversed(lines[-60:]):
        if l.startswith("Total transferred file size:"):
            stats["transferred"] = l.split(":",1)[1].strip()
        elif l.startswith("Total file size:"):
            stats["total"] = l.split(":",1)[1].strip()
        elif l.startswith("File list size:"):
            stats["file_list"] = l.split(":",1)[1].strip()
        elif l.startswith("sent ") and " bytes  received " in l:
            stats["throughput"] = l.strip()
    deleted = [l.split(None,1)[1] for l in itemized if l.startswith("*deleting")] [:max_items]
    return {"itemized_sample": sample, "counts": counts, "stats": stats, "deleted": deleted, "numbers": numbers}
    lines = [l for l in out_text.splitlines() if l.strip()]
    itemized = [l for l in lines if l[0] in {">","*","."} or l.startswith("deleting") or l.startswith("*deleting")]
    sample = itemized[:max_items]
    counts = {
        "created": sum(1 for l in itemized if "f+++++++++" in l),
        "changed": sum(1 for l in itemized if ">f" in l or ".d..t" in l or "f..t" in l or "f.st" in l),
        "deleted": sum(1 for l in itemized if "deleting" in l)}
    stats = {}
    for l in reversed(lines[-40:]):
        if l.startswith("Total transferred file size:"):
            stats["transferred"] = l.split(":",1)[1].strip()
        if l.startswith("Total file size:"):
            stats["total"] = l.split(":",1)[1].strip()
        if l.startswith("Number of files:"):
            stats["files"] = l.split(":",1)[1].strip()
        if l.startswith("Number of regular files transferred:"):
            stats["files_transferred"] = l.split(":",1)[1].strip()
        if l.startswith("sent ") and " bytes  received " in l:
            stats["throughput"] = l.strip()
    deleted = [l.split(None,1)[1] for l in itemized if l.startswith("*deleting")][:max_items]
    return {"itemized_sample": sample, "counts": counts, "stats": stats, "deleted": deleted}


def pre_cleanup(device: str):
    # Aggressive pre-clean: try our best to leave the target quiescent.
    try:
        swapoff_all(read_only=False)
    except Exception:
        pass
    try:
        # Unmount our standard mount points
        unmount_all("/mnt/nvme", force=True, read_only=False)
    except Exception:
        pass
    try:
        # Deactivate VG (idempotent)
        deactivate_vg("rp5vg", read_only=False)
    except Exception:
        pass
    try:
        # Close LUKS mapping if open
        close_luks("cryptroot", read_only=False)
    except Exception:
        pass
    # Extra belts: attempt dmsetup removal and lazy umounts on raw parts

    dm = probe(device, read_only=False)
    for p in (dm.p1, dm.p2, dm.p3):
        try:
            run(["umount","-l", p], check=False)
        except Exception:
            pass
    try:
        run(["dmsetup","remove","-f","cryptroot"], check=False)
    except Exception:
        pass
    # Wipe signatures on ESP/boot (safe; we re-mkfs); leave p3 wiping to partitioner
    for p in (dm.p1, dm.p2):
        try:
            run(["wipefs","-fa", p], check=False)
        except Exception:
            pass
    # Zap GPT to avoid ghost holders; partitioning will recreate fresh
    try:
        run(["sgdisk","--zap-all", device], check=False)
    except Exception:
        pass
    try:
        run(["partprobe", device], check=False)
        udev_settle()
    except Exception:
        pass
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ete_nvme_provision", add_help=True)
    p.add_argument("device")
    p.add_argument("--esp-mb", type=int, default=256)
    p.add_argument("--boot-mb", type=int, default=512)
    p.add_argument("--passphrase-file", default=None)
    p.add_argument("--plan", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reboot", action="store_true")
    p.add_argument("--do-postcheck", action="store_true")
    p.add_argument("--tpm-keyscript", action="store_true")
    p.add_argument("--yes", dest="assume_yes", action="store_true")
    p.add_argument("--skip-rsync", action="store_true")
    return p

def _same_underlying_disk(target_dev: str, root_src: str) -> bool:
    """Return True if target_dev appears to be the same underlying disk as the live root.
    We try lsblk pkname checks for both devices.
    """

    def _pkname(dev: str) -> str:
        try:
            out = os.popen(f"lsblk -no pkname {dev} 2>/dev/null").read().strip()
            return out or ""
        except Exception:
            return ""
    td = _pkname(target_dev) or os.path.basename(target_dev).lstrip('/')  # fallback
    rd = _pkname(root_src) or os.path.basename(root_src).lstrip('/')
    return td != "" and rd != "" and td == rd

def _holders_snapshot(device: str) -> str:
    try:
        import subprocess, shlex
        lsblk = subprocess.run(shlex.split(f"lsblk -o NAME,TYPE,MOUNTPOINT -n {device}"),
                               capture_output=True, text=True, timeout=5)
        sysfs = subprocess.run(["bash","-lc","ls -1 /sys/block/*/holders 2>/dev/null | xargs -I{} sh -lc 'echo {}; ls -l {}'"],
                               capture_output=True, text=True, timeout=5)
        out = []
        if lsblk.stdout: out.append(lsblk.stdout.strip())
        if sysfs.stdout: out.append(sysfs.stdout.strip())
        return "\n".join([x for x in out if x])
    except Exception:
        return ""


def main(argv=None) -> int:
    def confirm(device: str, assume_yes: bool):
        root_src = os.popen('findmnt -no SOURCE /').read().strip()
        print(f"[MATRIX] target={device} root={root_src}")
        if not assume_yes:
            ans = input(f"Type YES to wipe and provision {device}: ").strip()
            if ans != 'YES':
                print('Aborted.'); sys.exit(1)

    ap = build_parser()
    args = ap.parse_args(argv)
    mode = 'plan' if getattr(args, 'plan', False) else ('dry' if getattr(args, 'dry_run', False) else 'full')
    SYNC_PERFORMED = not getattr(args, 'skip_rsync', False)
    if mode == 'full' and getattr(args, 'skip_rsync', False):
        return _emit_result('FAIL_RSYNC_SKIPPED_FULLRUN', extra={'reason':'skip_rsync not allowed in full-run'})

    # postcheck-only mode: early exit, read-only checks
    try:
        trace('cli.args', device=args.device, plan=args.plan, read_only=args.dry_run, do_postcheck=args.do_postcheck, tpm_keyscript=args.tpm_keyscript, assume_yes=args.assume_yes, skip_rsync=args.skip_rsync)
    except Exception:
        pass
    flags = Flags(plan=args.plan, dry_run=args.dry_run, do_postcheck=args.do_postcheck,
                  tpm_keyscript=args.tpm_keyscript, assume_yes=args.assume_yes, skip_rsync=args.skip_rsync)
    plan = ProvisionPlan(device=args.device, esp_mb=args.esp_mb, boot_mb=args.boot_mb, passphrase_file=args.passphrase_file)
    # Device preflight
    if not os.path.exists(plan.device):
        return _emit_result('FAIL_INVALID_DEVICE', extra={'device': plan.device})

    # Safety rails
    root_src = os.popen('findmnt -no SOURCE /').read().strip()
    if _same_underlying_disk(plan.device, root_src):
        print(f"[FAIL] Target device {plan.device} resolves to same underlying disk as live root ({root_src}). Aborting.")
        sys.exit(1)
    if flags.skip_rsync:
        return _emit_result('FAIL_RSYNC_SKIPPED_FULLRUN', extra={'reason':'skip_rsync not allowed in full-run'})
    dm = probe(plan.device, read_only=True)


    # Second safety rail: recheck same-disk and capture holders
    if mode == 'full' and _same_underlying_disk(plan.device, root_src):
        return _emit_result('FAIL_SAFETY_GUARD', extra={'device': plan.device, 'root_src': root_src, 'holders': _holders_snapshot(plan.device)})
        # POSTCHECK_ONLY_BLOCK: non-destructive postcheck install + recovery doc
    if flags.do_postcheck and not flags.plan and not flags.dry_run:
        if (not args.passphrase_file or
            not os.path.isfile(args.passphrase_file) or
            os.path.getsize(args.passphrase_file) == 0):
            return _emit_result('FAIL_MISSING_PASSPHRASE', extra={'hint':'--do-postcheck requires a non-empty --passphrase-file'})
        dm = probe(plan.device, read_only=False)
        # Open LUKS and mount without changing layout
        open_luks(dm.p3, dm.luks_name, args.passphrase_file)
        mounts = mount_targets(dm.device, read_only=False, destructive=False); bind_mounts(mounts.mnt, read_only=False)
        p1_uuid = uuid_of(dm.p1, read_only=False)
        p2_uuid = uuid_of(dm.p2, read_only=False)
        luks_uuid = uuid_of(dm.p3, read_only=False)

        # Postcheck recovery doc
        try:
            import time, json, os
            rec_dir = os.path.expanduser('~/rp5/04_ARTIFACTS/recovery')
            os.makedirs(rec_dir, exist_ok=True)
            rec = {
                "device": plan.device,
                "uuids": {"esp": p1_uuid, "boot": p2_uuid, "luks": luks_uuid},
                "mount_point": mounts.mnt,
                "timestamp": int(time.time())
            }
            rec_path = os.path.join(rec_dir, f"recovery_{rec['timestamp']}.json")
            with open(rec_path, 'w', encoding='utf-8') as f:
                json.dump(rec, f, indent=2)
        except Exception as e:
            return _emit_result('FAIL_UNHANDLED', extra={'hint':'Failed to save recovery document', 'error': str(e)})
        if (not isinstance(luks_uuid, str)) or (len(luks_uuid.strip()) < 8):
            print('[FAIL] could not determine LUKS UUID for p3 (postcheck); aborting.')
            sys.exit(12)
        install_postboot_check(mounts.mnt)
        write_recovery_doc(mounts.mnt, luks_uuid)
        # Build JSON output similar to --plan
        out = {
            "flags": vars(flags),
            "postcheck": {
                "device": plan.device,
                "luks_uuid": luks_uuid,
                "installed": {
                    "postboot_check": "/usr/local/sbin/rp5-postboot-check",
                    "recovery_doc": "/root/RP5_RECOVERY.md"
                },
                "steps": [
                    "open_luks(p3, cryptroot, args.passphrase_file)",
                    "mount_targets(device)/bind",
                    "install_postboot_check",
                    "write_recovery_doc",
                    "unmount_all",
                    "close_luks"
                ]
            }
        }
        unmount_all(mounts.mnt, force=True, read_only=False)
        try:
            close_luks(dm.luks_name, read_only=False)
        except Exception:
            pass
    steps = [
        "swapoff_all()",
        f"kill_holders({dm.device})",
        f"apply_layout({dm.device},{plan.esp_mb},{plan.boot_mb})",
        "verify_layout(device)",
        f"format_luks({dm.p3},args.passphrase_file)",
        f"open_luks({dm.p3},{dm.luks_name},args.passphrase_file)",
        f"make_vg_lv({dm.vg},{dm.lv})",
        "mount_targets(device)/bind",
        "populate_esp(esp) + assert",
        "rsync_root(\1, exclude_boot=True)",
        "boot_plumbing(writes + assert UUID)",
        "initramfs(ensure,rebuild,verify)",
        "unmount_all(mnt)"
    ]


    # PLAN/DRY-RUN: strictly non-destructive
    if flags.plan or flags.dry_run:
        plan_out = {'device': plan.device, 'esp_mb': plan.esp_mb, 'boot_mb': plan.boot_mb, 'passphrase_file': plan.passphrase_file}
        _write_json_artifact('plan', {'plan': plan_out, 'flags': vars(flags)})
        kind = 'PLAN_OK' if flags.plan else 'DRYRUN_OK'
        _emit_result(kind, {'plan': plan_out, 'flags': vars(flags)})
    # FULL RUN


    # Pre-clean and layout
    swapoff_all(read_only=False)
    try:
        unmount_all("/mnt/nvme", force=True, read_only=False)
    except Exception:
        pass
    dm = probe(plan.device, read_only=False)
    kill_holders(dm.device, read_only=False)

    # Apply partitioning & filesystems
    apply_layout(dm.device, plan.esp_mb, plan.boot_mb)
    verify_layout(dm.device)

    # LUKS + LVM
    args.passphrase_file = os.path.expanduser(plan.passphrase_file) if plan.passphrase_file else None

    if args.passphrase_file is None or not os.path.isfile(args.passphrase_file) or os.path.getsize(args.passphrase_file) == 0:
        print("[FAIL] Invalid or missing --passphrase-file"); sys.exit(10)
    format_luks(dm.p3, args.passphrase_file)
    open_luks(dm.p3, dm.luks_name, args.passphrase_file)
    # Mount targets
    mounts = mount_targets(dm.device, read_only=False, destructive=False)
    bind_mounts(mounts.mnt, read_only=False)

    try:
        # Firmware & root sync
        populate_esp(mounts.esp, preserve_cmdline=True, preserve_config=True, read_only=False)
        assert_essentials(mounts.esp)
        _rs = rsync_root(\1, exclude_boot=True)
        _rs_meta = _rsync_meta(_rs)

        # Boot plumbing
        p1_uuid = uuid_of(dm.p1, read_only=False)
        p2_uuid = uuid_of(dm.p2, read_only=False)
        luks_uuid = uuid_of(dm.p3, read_only=False)

        # Postcheck recovery doc
        try:
            import time, json, os
            rec_dir = os.path.expanduser('~/rp5/04_ARTIFACTS/recovery')
            os.makedirs(rec_dir, exist_ok=True)
            rec = {
                "device": plan.device,
                "uuids": {"esp": p1_uuid, "boot": p2_uuid, "luks": luks_uuid},
                "mount_point": mounts.mnt,
                "timestamp": int(time.time())
            }
            rec_path = os.path.join(rec_dir, f"recovery_{rec['timestamp']}.json")
            with open(rec_path, 'w', encoding='utf-8') as f:
                json.dump(rec, f, indent=2)
        except Exception as e:
            return _emit_result('FAIL_UNHANDLED', extra={'hint':'Failed to save recovery document', 'error': str(e)})
        if (not isinstance(luks_uuid, str)) or (len(luks_uuid.strip()) < 8):
            print('[FAIL] could not determine LUKS UUID for p3; aborting.')
            sys.exit(12)
        write_fstab(mounts.mnt, p1_uuid, p2_uuid)
        write_crypttab(mounts.mnt, luks_uuid, plan.passphrase_file, keyscript_path=None)
        try:
            assert_crypttab_uuid(mounts.mnt, luks_uuid)
        except Exception:
            return _emit_result('FAIL_FIRMWARE_CHECK', extra={'hint':'/etc/crypttab UUID mismatch; update to LUKS UUID and rebuild initramfs'})
        write_cmdline(mounts.esp, luks_uuid)
        try:
            assert_cmdline_uuid(mounts.esp, luks_uuid)
        except Exception:
            return _emit_result('FAIL_FIRMWARE_CHECK', extra={'hint':'cmdline.txt UUID mismatch or missing; update cmdline.txt to LUKS and root UUIDs'})

        # Initramfs
        ensure_packages(mounts.mnt, read_only=False)
        rebuild(mounts.mnt, read_only=False)
        try:
            _ok_vif = verify_initramfs(mounts.esp)
            if not _ok_vif:
                return _emit_result('FAIL_INITRAMFS_VERIFY', extra={'hint':'Rebuild/initramfs mismatch; rebuild initramfs and verify cmdline/crypttab UUIDs'})
        except Exception:
            return _emit_result('FAIL_INITRAMFS_VERIFY', extra={'hint':'initramfs verification failed; rebuild initramfs and check UUIDs'})
            print(f" - Error: {e}")
            sys.exit(3)

        # Optional: post-boot checker and recovery doc
        if flags.do_postcheck:
            try:
                install_postboot_check(mounts.mnt)
                write_recovery_doc(mounts.mnt, luks_uuid)
            except Exception as e:
                print(f"[WARN] postcheck setup failed: {e}")

    except Exception:
        print('[DIAG] Provisioning error; mounted drives before cleanup:')
        try:
            _log_mounts()
        except Exception:
            pass
        try:
            unmount_all(mounts.mnt, force=True, read_only=False)
        except Exception:
            pass
        raise

# Teardown
    unmount_all(mounts.mnt, force=True, read_only=False)

    steps = [
        "swapoff_all()",
        f"kill_holders({dm.device})",
        f"apply_layout({dm.device},{plan.esp_mb},{plan.boot_mb})",
        "verify_layout(device)",
        f"format_luks({dm.p3},args.passphrase_file)",
        f"open_luks({dm.p3},{dm.luks_name},args.passphrase_file)",
        f"make_vg_lv({dm.vg},{dm.lv})",
        "mount_targets(device)/bind",
        "populate_esp(esp) + assert",
        "rsync_root(\1, exclude_boot=True)",
        "boot_plumbing(writes + assert UUID)",
        "initramfs(ensure,rebuild,verify)",
        "unmount_all(mnt)"
    ]
    out = {
        "result": "ETE_PREBOOT_OK",
        "sync_performed": True,
        "flags": vars(flags),
        "plan": {
            "device": plan.device,
            "esp_mb": plan.esp_mb,
            "boot_mb": plan.boot_mb,
            "passphrase_file": plan.passphrase_file
        },
        "uuids": {"p1": p1_uuid, "p2": p2_uuid, "luks": luks_uuid},
        "rsync": {"exit": _rs_meta.get("exit"), "err": _rs_meta.get("err"), "summary": _rsync_summarize(_rs_meta.get("out"))},
        "steps": steps
    }
    _emit_result('ETE_PREBOOT_OK', out)
if __name__ == "__main__":
    sys.exit(main())
