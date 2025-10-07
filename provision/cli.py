"""CLI entrypoint for the RP5 NVMe provisioner."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from .boot_plumbing import (
    assert_cmdline_uuid,
    assert_crypttab_uuid,
    write_cmdline,
    write_crypttab,
    write_fstab,
)
from . import safety
from .devices import kill_holders, probe, swapoff_all, uuid_of
from .executil import append_jsonl, run, trace, udev_settle
from .firmware import assert_essentials, populate_esp
from .initramfs import ensure_packages, rebuild, verify as verify_initramfs
from .luks_lvm import close_luks, deactivate_vg, format_luks, make_vg_lv, open_luks
from .model import Flags, ProvisionPlan
from .mounts import bind_mounts, mount_targets, unmount_all
from .partitioning import apply_layout, verify_layout
from .postcheck import cleanup_pycache, run_postcheck
from .postboot import install_postboot_check as install_postboot_heartbeat
from .recovery import write_recovery_doc
from .root_sync import rsync_root

RESULT_CODES: Dict[str, int] = {
    "PLAN_OK": 0,
    "DRYRUN_OK": 0,
    "ETE_PREBOOT_OK": 0,
    "ETE_DONE_OK": 0,
    "FAIL_SAFETY_GUARD": 2,
    "FAIL_MISSING_PASSPHRASE": 2,
    "FAIL_FIRMWARE_CHECK": 3,
    "FAIL_PARTITIONING": 4,
    "FAIL_LUKS": 5,
    "FAIL_LVM": 6,
    "FAIL_RSYNC": 7,
    "FAIL_POSTCHECK": 8,
    "FAIL_GENERIC": 9,
    "FAIL_RSYNC_SKIPPED_FULLRUN": 10,
    "FAIL_INITRAMFS_VERIFY": 11,
    "FAIL_UNHANDLED": 12,
    "FAIL_INVALID_DEVICE": 13,
    "POSTCHECK_OK": 14,
}


def _log_path(name: str) -> str:
    base = os.path.expanduser("~/rp5/03_LOGS")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(base, f"{name}_{ts}.json")


def _emit_result(
    kind: str,
    extra: Optional[Dict[str, Any]] = None,
    exit_code: Optional[int] = None,
) -> None:
    payload: Dict[str, Any] = {"result": kind, "ts": int(time.time())}
    if extra:
        payload.update(extra)
    append_jsonl(os.path.expanduser("~/rp5/03_LOGS/ete_nvme.jsonl"), payload)
    print(json.dumps(payload, indent=2))
    code = RESULT_CODES.get(kind, 1) if exit_code is None else exit_code
    raise SystemExit(code)


def _write_json_artifact(name: str, data: Dict[str, Any]) -> str:
    path = _log_path(name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return path


def _log_mounts() -> None:
    try:
        result = run(["findmnt", "-R", "/mnt/nvme"], check=False)
        if getattr(result, "out", None):
            print("[DIAG] findmnt -R /mnt/nvme:")
            print(result.out)
    except Exception:
        pass
    try:
        result = run(["lsblk", "-f"], check=False)
        if getattr(result, "out", None):
            print("[DIAG] lsblk -f:")
            print(result.out)
    except Exception:
        pass
    try:
        result = run(["mount"], check=False)
        if getattr(result, "out", None):
            lines = [
                ln
                for ln in result.out.splitlines()
                if "/mnt/nvme" in ln or "/mapper" in ln
            ]
            if lines:
                print("[DIAG] mount lines for /mnt/nvme and /mapper:")
                print("\n".join(lines))
    except Exception:
        pass


def _record_result(kind: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": kind, "ts": int(time.time())}
    if extra:
        payload.update(extra)
    append_jsonl(os.path.expanduser("~/rp5/03_LOGS/ete_nvme.jsonl"), payload)
    print(json.dumps(payload, indent=2))
    return payload


def _planned_steps(flags: Flags) -> list[str]:
    steps = [
        "swapoff_all()",
        "kill_holders(device)",
        "apply_layout(device, esp_mb, boot_mb)",
        "verify_layout(device)",
        "format_luks(p3, passphrase_file)",
        "open_luks(p3, luks_name, passphrase_file)",
        "make_vg_lv(vg, lv)",
        "mount_targets()/bind_mounts()",
        "populate_esp()/assert_essentials()",
    ]
    if flags.skip_rsync:
        steps.append("rsync_root(target, exclude_boot=True) [SKIPPED --skip-rsync]")
    else:
        steps.append("rsync_root(target, exclude_boot=True)")
    steps.extend([
        "write fstab/crypttab/cmdline + assert UUIDs",
        "ensure_packages()/rebuild()/verify_initramfs()",
    ])
    if flags.do_postcheck:
        steps.extend(
            [
                "install_postboot_heartbeat()/write_recovery_doc()",
                "cleanup_pycache()/run_postcheck()",
            ]
        )
    steps.append("unmount_all()/close_luks()/deactivate_vg()")
    steps.append("emit RESULT codes (ETE_PREBOOT_OK -> ETE_DONE_OK)")
    return steps


def _plan_payload(plan: ProvisionPlan, flags: Flags, root_src: str) -> Dict[str, Any]:
    dm = probe(plan.device, dry_run=True)
    state: Dict[str, Any] = {"root_source": root_src}
    holders = _holders_snapshot(plan.device)
    if holders:
        state["holders"] = holders
    try:
        lsblk = run(["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT", plan.device], check=False)
        if getattr(lsblk, "out", "").strip():
            state["lsblk"] = lsblk.out.strip()
    except Exception:
        pass
    state["same_underlying_disk"] = _same_underlying_disk(plan.device, root_src)
    plan_block = {
        "device": plan.device,
        "esp_mb": plan.esp_mb,
        "boot_mb": plan.boot_mb,
        "passphrase_file": plan.passphrase_file,
        "device_map": vars(dm),
    }
    payload: Dict[str, Any] = {
        "mode": "plan" if flags.plan else ("dry-run" if flags.dry_run else "full"),
        "plan": plan_block,
        "flags": vars(flags),
        "state": state,
        "steps": _planned_steps(flags),
        "rsync": {
            "skip": flags.skip_rsync,
            "exclude_boot": True,
        },
        "postcheck": {"requested": flags.do_postcheck},
        "timestamp": int(time.time()),
    }
    return payload


def _rsync_meta(res: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"exit": None, "out": None, "err": None, "warning": None}
    try:
        if hasattr(res, "returncode"):
            meta["exit"] = res.returncode
        if hasattr(res, "output") and res.output:
            meta["out"] = (
                res.output if isinstance(res.output, str) else res.output.decode(errors="ignore")
            )
        if hasattr(res, "stderr") and res.stderr:
            meta["err"] = (
                res.stderr if isinstance(res.stderr, str) else res.stderr.decode(errors="ignore")
            )
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


def _rsync_summarize(out_text: str, max_items: int = 30) -> Dict[str, Any]:
    if not out_text:
        return {
            "itemized_sample": [],
            "counts": {},
            "stats": {},
            "deleted": [],
            "numbers": [],
            "numbers_block": [],
        }

    lines = out_text.splitlines()
    itemized = [
        line
        for line in lines
        if line.strip()
        and (
            line.startswith("deleting")
            or line.startswith("*deleting")
            or line[0] in {">", "*", "."}
        )
    ]
    sample = itemized[:max_items]
    numbers = [line for line in lines if line.startswith("Number of ")]
    idx = next((i for i, line in enumerate(lines) if line.startswith("Number of ")), None)
    numbers_block = [line for line in (lines[idx:] if idx is not None else []) if line.strip()]
    counts = {
        "created": sum(1 for line in itemized if "f+++++++++" in line),
        "changed": sum(
            1
            for line in itemized
            if any(marker in line for marker in (">f", ".d..t", "f..t", "f.st"))
        ),
        "deleted": sum(1 for line in itemized if "deleting" in line),
    }
    stats: Dict[str, Any] = {}
    for line in lines[-80:]:
        if line.startswith("Total transferred file size:"):
            stats["transferred"] = line.split(":", 1)[1].strip()
        elif line.startswith("Total file size:"):
            stats["total"] = line.split(":", 1)[1].strip()
        elif line.startswith("File list size:"):
            stats["file_list"] = line.split(":", 1)[1].strip()
        elif line.startswith("sent ") and " bytes  received " in line:
            stats["throughput"] = line.strip()
    deleted = [line.split(None, 1)[1] for line in itemized if line.startswith("*deleting")][:max_items]
    return {
        "itemized_sample": sample,
        "counts": counts,
        "stats": stats,
        "deleted": deleted,
        "numbers": numbers,
        "numbers_block": numbers_block,
    }


def pre_cleanup(device: str) -> None:
    try:
        swapoff_all()
    except Exception:
        pass
    try:
        unmount_all("/mnt/nvme")
    except Exception:
        pass
    try:
        deactivate_vg("rp5vg")
    except Exception:
        pass
    try:
        close_luks("cryptroot")
    except Exception:
        pass

    dm = probe(device)
    for part in (dm.p1, dm.p2, dm.p3):
        try:
            run(["umount", "-l", part], check=False)
        except Exception:
            pass
    try:
        run(["dmsetup", "remove", "-f", "cryptroot"], check=False)
    except Exception:
        pass
    for part in (dm.p1, dm.p2):
        try:
            run(["wipefs", "-fa", part], check=False)
        except Exception:
            pass
    try:
        run(["sgdisk", "--zap-all", device], check=False)
    except Exception:
        pass
    try:
        run(["partprobe", device], check=False)
        udev_settle()
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ete_nvme_provision", add_help=True)
    parser.add_argument("device")
    parser.add_argument("--esp-mb", type=int, default=256)
    parser.add_argument("--boot-mb", type=int, default=512)
    parser.add_argument("--passphrase-file", default=None)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reboot", action="store_true")
    parser.add_argument("--do-postcheck", action="store_true")
    parser.add_argument("--tpm-keyscript", action="store_true")
    parser.add_argument("--yes", dest="assume_yes", action="store_true")
    parser.add_argument("--skip-rsync", action="store_true")
    return parser


def _same_underlying_disk(target_dev: str, root_src: str) -> bool:
    def _pkname(dev: str) -> str:
        try:
            out = os.popen(f"lsblk -no pkname {shlex.quote(dev)} 2>/dev/null").read().strip()
            return out or ""
        except Exception:
            return ""

    td = _pkname(target_dev) or os.path.basename(target_dev).lstrip("/")
    rd = _pkname(root_src) or os.path.basename(root_src).lstrip("/")
    return bool(td and rd and td == rd)


def _holders_snapshot(device: str) -> str:
    try:
        lsblk = subprocess.run(
            ["lsblk", "-o", "NAME,TYPE,MOUNTPOINT", "-n", device],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sysfs = subprocess.run(
            [
                "bash",
                "-lc",
                "ls -1 /sys/block/*/holders 2>/dev/null | xargs -I{} sh -lc 'echo {}; ls -l {}'",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out: list[str] = []
        if lsblk.stdout:
            out.append(lsblk.stdout.strip())
        if sysfs.stdout:
            out.append(sysfs.stdout.strip())
        return "\n".join(x for x in out if x)
    except Exception:
        return ""


def _require_passphrase(path: Optional[str]) -> str:
    if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
        _emit_result(
            "FAIL_MISSING_PASSPHRASE",
            extra={"hint": "--passphrase-file must reference a non-empty file"},
        )
    return os.path.abspath(path)


def _run_postcheck_only(plan: ProvisionPlan, flags: Flags, passphrase_file: str) -> None:
    dm = probe(plan.device)
    mounts = None
    open_luks(dm.p3, dm.luks_name, passphrase_file)
    mounts = mount_targets(dm.device, dry_run=False, destructive=False)
    bind_mounts(mounts.mnt, read_only=True)
    try:
        p1_uuid = uuid_of(dm.p1)
        p2_uuid = uuid_of(dm.p2)
        luks_uuid = uuid_of(dm.p3)
        if not isinstance(luks_uuid, str) or len(luks_uuid.strip()) < 8:
            raise RuntimeError("could not determine LUKS UUID")

        heartbeat_meta = install_postboot_heartbeat(mounts.mnt)
        write_recovery_doc(mounts.mnt, luks_uuid)

        cleanup = cleanup_pycache(mounts.mnt)
        postcheck = run_postcheck(mounts.mnt, luks_uuid, p1_uuid)

        rec_dir = os.path.expanduser("~/rp5/04_ARTIFACTS/recovery")
        os.makedirs(rec_dir, exist_ok=True)
        rec = {
            "device": plan.device,
            "uuids": {"esp": p1_uuid, "boot": p2_uuid, "luks": luks_uuid},
            "mount_point": mounts.mnt,
            "timestamp": int(time.time()),
        }
        rec_path = os.path.join(rec_dir, f"recovery_{rec['timestamp']}.json")
        with open(rec_path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)

        out = {
            "flags": vars(flags),
            "postcheck": {
                "device": plan.device,
                "luks_uuid": luks_uuid,
                "installed": {
                    "heartbeat": heartbeat_meta,
                    "recovery_doc": "/root/RP5_RECOVERY.md",
                },
                "cleanup": cleanup,
                "report": postcheck,
                "steps": [
                    "open_luks(p3, cryptroot, passphrase_file)",
                    "mount_targets(device)/bind",
                    "install_postboot_heartbeat",
                    "write_recovery_doc",
                    "unmount_all",
                    "close_luks",
                ],
            },
        }
    except Exception as exc:  # noqa: BLE001
        _emit_result(
            "FAIL_POSTCHECK",
            extra={"hint": "Failed postcheck-only flow", "error": str(exc)},
        )
    finally:
        if mounts is not None:
            try:
                unmount_all(mounts.mnt, boot=mounts.boot, esp=mounts.esp)
            except Exception:
                pass
        try:
            close_luks(dm.luks_name)
        except Exception:
            pass
    _emit_result("POSTCHECK_OK", out)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    mode = "plan" if args.plan else ("dry" if args.dry_run else "full")
    sync_performed = not args.skip_rsync

    try:
        trace(
            "cli.args",
            device=args.device,
            plan=args.plan,
            dry_run=args.dry_run,
            do_postcheck=args.do_postcheck,
            tpm_keyscript=args.tpm_keyscript,
            assume_yes=args.assume_yes,
            skip_rsync=args.skip_rsync,
        )
    except Exception:
        pass

    flags = Flags(
        plan=args.plan,
        dry_run=args.dry_run,
        skip_rsync=args.skip_rsync,
        do_postcheck=args.do_postcheck,
        tpm_keyscript=args.tpm_keyscript,
        assume_yes=args.assume_yes,
    )
    plan = ProvisionPlan(
        device=args.device,
        esp_mb=args.esp_mb,
        boot_mb=args.boot_mb,
        passphrase_file=args.passphrase_file,
    )

    if not os.path.exists(plan.device):
        _emit_result("FAIL_INVALID_DEVICE", extra={"device": plan.device})

    ok, reason = safety.guard_not_live_disk(plan.device)
    if not ok:
        _emit_result("FAIL_SAFETY_GUARD", extra={"device": plan.device, "reason": reason})

    root_src = os.popen("findmnt -no SOURCE /").read().strip()
    if _same_underlying_disk(plan.device, root_src):
        extra = {"device": plan.device, "root_src": root_src}
        if mode == "full":
            extra["holders"] = _holders_snapshot(plan.device)
        _emit_result("FAIL_SAFETY_GUARD", extra=extra)

    if mode == "full" and args.skip_rsync:
        _emit_result(
            "FAIL_RSYNC_SKIPPED_FULLRUN",
            extra={"reason": "--skip-rsync is not allowed in full run"},
        )

    if flags.do_postcheck and not flags.plan and not flags.dry_run:
        passphrase_file = _require_passphrase(plan.passphrase_file)
        _run_postcheck_only(plan, flags, passphrase_file)

    if flags.plan or flags.dry_run:
        plan_payload = _plan_payload(plan, flags, root_src)
        artifact_path = _write_json_artifact("plan", plan_payload)
        result_kind = "PLAN_OK" if flags.plan else "DRYRUN_OK"
        result_payload = dict(plan_payload)
        result_payload["artifact"] = artifact_path
        _emit_result(result_kind, result_payload)

    passphrase_file = _require_passphrase(plan.passphrase_file)

    try:
        pre_cleanup(plan.device)
    except Exception:
        pass

    dm = probe(plan.device)

    try:
        swapoff_all()
        unmount_all("/mnt/nvme")
    except Exception:
        pass

    dm = probe(plan.device)
    kill_holders(dm.device)

    apply_layout(dm.device, plan.esp_mb, plan.boot_mb)
    verify_layout(dm.device)

    format_luks(dm.p3, passphrase_file)
    open_luks(dm.p3, dm.luks_name, passphrase_file)
    make_vg_lv(dm.vg, dm.lv)

    mounts = mount_targets(dm.device, dry_run=False, destructive=True)
    bind_mounts(mounts.mnt, read_only=False)

    rsync_meta: Dict[str, Any] = {"exit": 0, "err": None, "out": None, "warning": None}
    postcheck_report: Optional[Dict[str, Any]] = None
    cleanup_stats: Optional[Dict[str, Any]] = None
    heartbeat_meta: Optional[Dict[str, Any]] = None
    recovery_doc_path: Optional[str] = None
    try:
        populate_esp(mounts.esp, preserve_cmdline=True, preserve_config=True, dry_run=False)
        assert_essentials(mounts.esp)

        rsync_result = rsync_root(mounts.mnt, dry_run=False, exclude_boot=True)
        rsync_meta = _rsync_meta(rsync_result)

        p1_uuid = uuid_of(dm.p1)
        p2_uuid = uuid_of(dm.p2)
        luks_uuid = uuid_of(dm.p3)
        if not isinstance(luks_uuid, str) or len(luks_uuid.strip()) < 8:
            raise RuntimeError("could not determine LUKS UUID")

        write_fstab(mounts.mnt, p1_uuid, p2_uuid)
        write_crypttab(mounts.mnt, luks_uuid, passphrase_file, keyscript_path=None)
        assert_crypttab_uuid(mounts.mnt, luks_uuid)
        write_cmdline(mounts.esp, luks_uuid)
        assert_cmdline_uuid(mounts.esp, luks_uuid)

        ensure_packages(mounts.mnt)
        rebuild(mounts.mnt)
        if not verify_initramfs(mounts.esp):
            _emit_result(
                "FAIL_INITRAMFS_VERIFY",
                extra={"hint": "initramfs verification failed; rebuild and re-check UUIDs"},
            )

        if flags.do_postcheck:
            try:
                heartbeat_meta = install_postboot_heartbeat(mounts.mnt)
                write_recovery_doc(mounts.mnt, luks_uuid)
                recovery_doc_path = os.path.join(mounts.mnt, "root", "RP5_RECOVERY.md")
                cleanup_stats = cleanup_pycache(mounts.mnt)
                postcheck_report = run_postcheck(mounts.mnt, luks_uuid, p1_uuid)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] postcheck setup failed: {exc}")

    except Exception as exc:  # noqa: BLE001
        print(f"[DIAG] Provisioning error: {exc}")
        try:
            _log_mounts()
        except Exception:
            pass
        try:
            unmount_all(mounts.mnt, boot=mounts.boot, esp=mounts.esp)
        except Exception:
            pass
        raise

    unmount_all(mounts.mnt, boot=mounts.boot, esp=mounts.esp)

    try:
        close_luks(dm.luks_name)
        deactivate_vg(dm.vg)
    except Exception:
        pass

    planned_steps = _planned_steps(flags)

    result_payload = {
        "sync_performed": sync_performed,
        "flags": vars(flags),
        "plan": {
            "device": plan.device,
            "esp_mb": plan.esp_mb,
            "boot_mb": plan.boot_mb,
            "passphrase_file": plan.passphrase_file,
        },
        "uuids": {"p1": p1_uuid, "p2": p2_uuid, "luks": luks_uuid},
        "rsync": {
            "exit": rsync_meta.get("exit"),
            "warning": rsync_meta.get("warning"),
            "err": rsync_meta.get("err"),
            "summary": _rsync_summarize(rsync_meta.get("out") or ""),
        },
        "postcheck": {
            "requested": flags.do_postcheck,
            "heartbeat": heartbeat_meta,
            "recovery_doc": recovery_doc_path,
            "report": postcheck_report,
            "cleanup": cleanup_stats,
        },
        "steps": planned_steps,
    }
    preboot_payload = dict(result_payload)
    preboot_payload["phase"] = "preboot"
    _record_result("ETE_PREBOOT_OK", preboot_payload)

    final_payload = dict(result_payload)
    final_payload["phase"] = "completed"
    _emit_result("ETE_DONE_OK", final_payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
