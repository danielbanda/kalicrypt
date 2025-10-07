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
from .luks_lvm import (
    activate_vg,
    close_luks,
    deactivate_vg,
    format_luks,
    make_vg_lv,
    open_luks,
)
from .model import Flags, ProvisionPlan
from .mounts import mount_targets_safe, bind_mounts, mount_targets, unmount_all
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
    "FAIL_MKFS": 6,
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
    payload = dict(data)
    payload["artifact"] = path
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass
    return path


def _log_mounts() -> None:
    try:
        result = run(["findmnt", "-R", "/mnt/nvme"], check=False)
        # if getattr(result, "out", None):
        #     print("[DIAG] findmnt -R /mnt/nvme:")
        #     print(result.out)
    except Exception:
        pass
    try:
        result = run(["lsblk", "-f"], check=False)
        # if getattr(result, "out", None):
        #     print("[DIAG] lsblk -f:")
        #     print(result.out)
    except Exception:
        pass
    try:
        result = run(["mount"], check=False)
        # if getattr(result, "out", None):
        #     lines = [
        #         ln
        #         for ln in result.out.splitlines()
        #         if "/mnt/nvme" in ln or "/mapper" in ln
        #     ]
        #     if lines:
        #         print("[DIAG] mount lines for /mnt/nvme and /mapper:")
        #         print("\n".join(lines))
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
    state["holders"] = holders.splitlines() if holders else []
    try:
        lsblk = run(
            [
                "lsblk",
                "-o",
                "NAME,TYPE,SIZE,RO,DISC-ALN,DISC-GRAN,DISC-MAX,DISC-ZERO,MOUNTPOINT",
                plan.device,
            ],
            check=False,
        )
        out = (getattr(lsblk, "out", "") or "").strip()
        if out:
            state["lsblk"] = out.splitlines()
    except Exception:
        pass
    try:
        lsblk_verbose = run(["lsblk", "-O", plan.device], check=False)
        if getattr(lsblk_verbose, "out", "").strip():
            state["lsblk_verbose"] = lsblk_verbose.out.strip().splitlines()
    except Exception:
        pass
    state["same_underlying_disk"] = _same_underlying_disk(plan.device, root_src)
    plan_block = {
        "device": plan.device,
        "esp_mb": plan.esp_mb,
        "boot_mb": plan.boot_mb,
        "passphrase_file": plan.passphrase_file,
        "device_map": vars(dm),
        "detected": {
            "vg": dm.vg,
            "lv": dm.lv,
            "root_lv_path": dm.root_lv_path,
            "root_mapper": dm.root_lv_path or f"/dev/mapper/{dm.vg}-{dm.lv}",
        },
    }
    payload: Dict[str, Any] = {
        "mode": "plan" if flags.plan else ("dry-run" if flags.dry_run else "full"),
        "plan": plan_block,
        "flags": vars(flags),
        "uuids": {"p1": None, "p2": None, "luks": None},
        "state": state,
        "steps": _planned_steps(flags),
        "rsync": {
            "skip": flags.skip_rsync,
            "exclude_boot": True,
        },
        "initramfs": {"image": None},
        "postcheck": {
            "requested": flags.do_postcheck,
            **({"offer": "--do-postcheck"} if not flags.do_postcheck else {}),
        },
        "timestamp": int(time.time()),
    }
    return payload


def _pre_sync_snapshot(max_mount_lines: int = 20) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    try:
        df_out = run(["df", "-h"], check=False)
        if getattr(df_out, "out", "").strip():
            snapshot["df_h"] = df_out.out.strip().splitlines()
    except Exception:
        pass
    try:
        mount_cmd = f"mount | head -n {max(1, max_mount_lines)}"
        mounts = run(["bash", "-lc", mount_cmd], check=False)
        if getattr(mounts, "out", "").strip():
            snapshot["mount_sample"] = mounts.out.strip().splitlines()
    except Exception:
        pass
    try:
        with open("/etc/hostname", "r", encoding="utf-8") as fh:
            snapshot["hostname"] = fh.read().strip()
    except Exception:
        pass
    return snapshot


def _rsync_meta(res: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"exit": None, "out": None, "err": None, "warning": False, "note": None}
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
        meta["warning"] = True
        meta["note"] = "partial transfer (vanished or permission-restricted files)"
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


def _normalize_passphrase_path(path: Optional[str]) -> Optional[str]:
    """Return an absolute filesystem path for ``--passphrase-file`` inputs."""

    if not path:
        return None
    expanded = os.path.expanduser(path)
    return os.path.abspath(expanded)


def _require_passphrase(path: Optional[str], context: str = "default") -> str:
    def _hint(reason: str) -> Dict[str, Any]:
        base = "--passphrase-file must reference a non-empty file"
        if context == "postcheck-only":
            base = (
                "--do-postcheck still needs a valid --passphrase-file so the LUKS volume "
                "can be opened read-only"
            )
        return {"hint": base, "reason": reason}

    normalized = _normalize_passphrase_path(path)

    if not normalized or not os.path.isfile(normalized):
        _emit_result("FAIL_MISSING_PASSPHRASE", extra=_hint("missing"))
    if os.path.getsize(normalized) == 0:
        _emit_result("FAIL_MISSING_PASSPHRASE", extra=_hint("empty"))
    return normalized


def _run_postcheck_only(plan: ProvisionPlan, flags: Flags, passphrase_file: str) -> None:
    dm = probe(plan.device)
    mounts = None
    open_luks(dm.p3, dm.luks_name, passphrase_file)
    activate_vg(dm.vg)
    mounts = mount_targets_safe(dm.device, dry_run=False)
    bind_mounts(mounts.mnt)
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
                unmount_all(mounts.mnt)
            except Exception:
                pass
        try:
            deactivate_vg(dm.vg)
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
    normalized_passphrase = _normalize_passphrase_path(args.passphrase_file)

    plan = ProvisionPlan(
        device=args.device,
        esp_mb=args.esp_mb,
        boot_mb=args.boot_mb,
        passphrase_file=normalized_passphrase,
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
        passphrase_file = _require_passphrase(plan.passphrase_file, context="postcheck-only")
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
    run(["vgchange","-ay", dm.vg], check=False)
    run(["dmsetup","mknodes"], check=False)
    udev_settle()
    make_vg_lv(dm.vg, dm.lv)

    mounts = mount_targets(dm.device, dry_run=False)
    bind_mounts(mounts.mnt)

    rsync_meta: Dict[str, Any] = {"exit": 0, "err": None, "out": None, "warning": False, "note": None}
    pre_sync_snapshot: Dict[str, Any] = {}
    postcheck_report: Optional[Dict[str, Any]] = None
    cleanup_stats: Optional[Dict[str, Any]] = None
    heartbeat_meta: Optional[Dict[str, Any]] = None
    recovery_doc_path: Optional[str] = None
    root_mapper_path: Optional[str] = None
    initramfs_image: Optional[str] = None
    try:
        populate_esp(mounts.esp, preserve_cmdline=True, preserve_config=True, dry_run=False)
        assert_essentials(mounts.esp)

        pre_sync_snapshot = _pre_sync_snapshot()
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
        root_mapper_path = dm.root_lv_path or f"/dev/mapper/{dm.vg}-{dm.lv}"
        write_cmdline(
            mounts.esp,
            luks_uuid,
            root_mapper=root_mapper_path,
            vg=dm.vg,
            lv=dm.lv,
        )
        assert_cmdline_uuid(mounts.esp, luks_uuid, root_mapper=root_mapper_path)

        ensure_packages(mounts.mnt)
        rebuild(mounts.mnt)
        initramfs_image = verify_initramfs(mounts.esp)

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
            unmount_all(mounts.mnt)
        except Exception:
            pass
        raise

    planned_steps = _planned_steps(flags)

    try:
        _log_mounts()
    except Exception:
        pass

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
        "detected": {
            "vg": dm.vg,
            "lv": dm.lv,
            "root_lv_path": dm.root_lv_path,
            "root_mapper": root_mapper_path,
        },
        "pre_sync": pre_sync_snapshot,
        "rsync": {
            "exit": rsync_meta.get("exit"),
            "warning": rsync_meta.get("warning"),
            "note": rsync_meta.get("note"),
            "err": rsync_meta.get("err"),
            "summary": _rsync_summarize(rsync_meta.get("out") or ""),
        },
        "initramfs": {"image": initramfs_image},
        "postcheck": {
            "requested": flags.do_postcheck,
            "heartbeat": heartbeat_meta,
            "recovery_doc": recovery_doc_path,
            "report": postcheck_report,
            "cleanup": cleanup_stats,
        },
        "steps": planned_steps,
    }
    if not flags.do_postcheck:
        result_payload["postcheck"]["offer"] = "--do-postcheck"
    artifact_path = _write_json_artifact("full", result_payload)
    result_payload["artifact"] = artifact_path
    preboot_payload = dict(result_payload)
    preboot_payload["phase"] = "preboot"
    _record_result("ETE_PREBOOT_OK", preboot_payload)

    try:
        unmount_all(mounts.mnt)
    except Exception:
        pass

    try:
        close_luks(dm.luks_name)
        deactivate_vg(dm.vg)
    except Exception:
        pass

    try:
        _log_mounts()
    except Exception:
        pass

    final_payload = dict(result_payload)
    final_payload["phase"] = "completed"
    _emit_result("ETE_DONE_OK", final_payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
