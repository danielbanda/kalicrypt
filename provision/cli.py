"""CLI entrypoint for the RP5 NVMe provisioner."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import safety
from .boot_plumbing import (
    assert_cmdline_uuid,
    assert_crypttab_uuid,
    write_cmdline,
    write_config,
    write_crypttab,
    write_fstab,
)
from .devices import kill_holders, probe, swapoff_all, uuid_of
from .executil import append_jsonl, resolve_log_path, run, trace, udev_settle
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
from .postboot import install_postboot_check as install_postboot_heartbeat
from .postcheck import cleanup_pycache, run_postcheck
from .recovery import write_recovery_doc
from .root_sync import parse_rsync_stats, rsync_root
from .verification import InitramfsVerificationError, require_boot_surface_ok

RESULT_CODES: Dict[str, int] = {
    "PLAN_OK": 0,
    "DRYRUN_OK": 0,
    "ETE_PREBOOT_OK": 0,
    "ETE_DONE_OK": 0,
    "FAIL_SAFETY_GUARD": 2,
    "FAIL_LIVE_DISK_GUARD": 2,
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

RESULT_LOG_PATH: Optional[str] = None
_LOG_ANNOUNCED = False


def _result_log_path() -> str:
    global RESULT_LOG_PATH
    if RESULT_LOG_PATH:
        return RESULT_LOG_PATH
    path = resolve_log_path()
    if not path:
        base = os.path.expanduser("/home/admin/rp5/03_LOGS")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass
        path = os.path.join(base, "ete_nvme.jsonl")
    RESULT_LOG_PATH = path
    return path


def _announce_log_path() -> str:
    global _LOG_ANNOUNCED
    path = _result_log_path()
    if not _LOG_ANNOUNCED:
        if path:
            try:
                trace("cli.log_path", path=path)
            except Exception:
                pass
        try:
            sys.stdout.flush()
        except Exception:
            pass
        _LOG_ANNOUNCED = True
    return path


def _safety_snapshot(device: str) -> Dict[str, Any]:
    def _capture(cmd: list[str]) -> str:
        try:
            return subprocess.check_output(cmd, text=True).strip()
        except Exception:
            return ""

    root_src = _capture(["findmnt", "-no", "SOURCE", "/"]) or ""
    boot_src = _capture(["findmnt", "-no", "SOURCE", "/boot"]) or ""
    target_pkname = _capture(["lsblk", "-no", "PKNAME", device]) or ""
    if not target_pkname:
        target_pkname = os.path.basename(device).rstrip("0123456789")
    snapshot = {
        "root_src": root_src,
        "boot_src": boot_src,
        "target_device": device,
        "target_pkname": target_pkname,
    }
    return snapshot


def _emit_safety_check(snapshot: Dict[str, Any]) -> None:
    payload = {"ts": int(time.time()), "event": "SAFETY_CHECK", **snapshot}
    append_jsonl(_result_log_path(), payload)
    try:
        trace("cli.safety_check", **snapshot)
    except Exception:
        pass
    # try:
    #     print(f"safety_check={json.dumps(snapshot, sort_keys=True)}")
    #     sys.stdout.flush()
    # except Exception:
    #     pass


def _log_path(name: str) -> str:
    base = os.path.expanduser("/home/admin/rp5/03_LOGS")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(base, f"{name}_{ts}.json")


def _git_rev_parse(ref: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", ref],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except Exception:
        return None


def _version_metadata() -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "sha_main": _git_rev_parse("HEAD"),
        "sha_cli": _git_rev_parse("HEAD:provision/cli.py"),
        "ts": ts,
        "branch": "in-mem",
    }


def _emit_version_stamp(meta: Dict[str, Any]) -> Dict[str, Any]:
    base = os.path.expanduser("/home/admin/rp5/03_LOGS")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{meta['ts']}.ver")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        #print(f"version_stamp={path}")
        enriched = dict(meta)
        enriched["path"] = path
        return enriched
    except Exception:
        print("version_stamp=<unavailable>", file=sys.stderr)
        enriched = dict(meta)
        enriched["path"] = None
        return enriched


def _emit_result(
        kind: str,
        extra: Optional[Dict[str, Any]] = None,
        exit_code: Optional[int] = None,
) -> None:
    payload: Dict[str, Any] = {"result": kind, "ts": int(time.time())}
    if extra:
        payload.update(extra)
    if not kind.endswith("_OK"):
        meta = _emit_version_stamp(_version_metadata())
        payload["version"] = meta
    append_jsonl(_result_log_path(), payload)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
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
    append_jsonl(_result_log_path(), payload)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)
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


def _plan_payload(
    plan: ProvisionPlan,
    flags: Flags,
    root_src: str,
    safety_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
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
        "safety_check": safety_snapshot,
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
    meta: Dict[str, Any] = {
        "exit": None,
        "out": None,
        "err": None,
        "warning": False,
        "note": None,
    }
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
    meta["duration_sec"] = getattr(res, "duration", None)
    meta["retries"] = getattr(res, "retries", 0)
    out_text = meta.get("out") or ""
    summary = _rsync_summarize(out_text)
    stats = parse_rsync_stats(out_text)
    required_keys = ("files_transferred", "total_file_size", "throughput_line", "speedup")
    summary_stats = summary.setdefault("stats", {})
    meta_stats = {}
    for key in required_keys:
        value = stats.get(key)
        summary_stats.setdefault(key, value)
        meta_stats[key] = value
    meta["summary"] = summary
    meta["stats"] = meta_stats
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


def _timing_from_packages(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not meta:
        return {}
    timing: Dict[str, Any] = {}
    update = meta.get("update") or {}
    if update:
        timing["update_sec"] = update.get("duration_sec")
    packages = []
    for entry in meta.get("installs", []) or []:
        packages.append(
            {
                "package": entry.get("package"),
                "check_sec": entry.get("check_duration_sec"),
                "install_sec": entry.get("install_duration_sec"),
            }
        )
    if packages:
        timing["packages"] = packages
    if meta.get("retries"):
        timing["retries"] = meta.get("retries")
    return timing


def _timing_from_rebuild(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not meta:
        return {}
    timing: Dict[str, Any] = {}
    attempts = []
    for attempt in meta.get("attempts", []) or []:
        attempts.append(
            {
                "mode": attempt.get("mode"),
                "rc": attempt.get("rc"),
                "duration_sec": attempt.get("duration_sec"),
            }
        )
    if attempts:
        timing["attempts"] = attempts
    copy_meta = meta.get("copy") or {}
    if copy_meta:
        timing["copy_sec"] = copy_meta.get("duration_sec")
    list_meta = meta.get("list") or {}
    if list_meta:
        timing["list_sec"] = list_meta.get("duration_sec")
    if meta.get("retries"):
        timing["retries"] = meta.get("retries")
    return timing


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


def _run_postcheck_only(
    plan: ProvisionPlan,
    flags: Flags,
    passphrase_file: str,
    safety_snapshot: Dict[str, Any],
    log_path: Optional[str],
) -> None:  # pragma: no cover - hardware flow
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
        recovery_meta = write_recovery_doc(mounts.mnt, luks_uuid)

        cleanup = cleanup_pycache(mounts.mnt)
        try:
            postcheck = run_postcheck(mounts.mnt, luks_uuid, p1_uuid)
        except InitramfsVerificationError as exc:
            _emit_result(
                "FAIL_INITRAMFS_VERIFY",
                extra={"why": exc.why, "checks": exc.result},
            )

        rec_dir = os.path.expanduser("/home/admin/rp5/04_ARTIFACTS/recovery")
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
            "log_path": log_path or _result_log_path(),
            "safety_check": safety_snapshot,
            "postcheck": {
                "device": plan.device,
                "luks_uuid": luks_uuid,
                "installed": {
                    "heartbeat": heartbeat_meta,
                    "recovery_doc": recovery_meta,
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


def _main_impl(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - exercised via manual CLI
    parser = build_parser()
    args = parser.parse_args(argv)
    mode = "plan" if args.plan else ("dry" if args.dry_run else "full")
    sync_performed = not args.skip_rsync

    log_path = _announce_log_path()

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

    safety_snapshot = _safety_snapshot(plan.device)
    _emit_safety_check(safety_snapshot)

    ok, reason = safety.guard_not_live_disk(plan.device)
    if not ok:
        extra = dict(safety_snapshot)
        extra["reason"] = reason or "live disk guard triggered"
        _emit_result("FAIL_LIVE_DISK_GUARD", extra=extra)

    root_src = safety_snapshot.get("root_src", "")
    if _same_underlying_disk(plan.device, root_src):
        extra = dict(safety_snapshot)
        extra["reason"] = "target shares underlying disk with live root"
        if mode == "full":
            extra["holders"] = _holders_snapshot(plan.device)
        _emit_result("FAIL_LIVE_DISK_GUARD", extra=extra)

    if mode == "full" and args.skip_rsync:
        _emit_result(
            "FAIL_RSYNC_SKIPPED_FULLRUN",
            extra={"reason": "--skip-rsync is not allowed in full run"},
        )

    if flags.do_postcheck and not flags.plan and not flags.dry_run:
        passphrase_file = _require_passphrase(plan.passphrase_file, context="postcheck-only")
        _run_postcheck_only(plan, flags, passphrase_file, safety_snapshot, log_path)

    if flags.plan or flags.dry_run:
        plan_payload = _plan_payload(plan, flags, root_src, safety_snapshot)
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
    run(["vgchange", "-ay", dm.vg], check=False)
    run(["dmsetup", "mknodes"], check=False)
    # Wait for /dev/mapper/rp5vg-root to appear
    for _ in range(8):
        if os.path.exists(f"/dev/mapper/{dm.vg}-{dm.lv}"):
            break
        time.sleep(0.25)
        udev_settle()
    make_vg_lv(dm.vg, dm.lv)

    mounts = mount_targets(dm.device, dry_run=False)
    bind_mounts(mounts.mnt)

    rsync_meta: Dict[str, Any] = {"exit": 0, "err": None, "out": None, "warning": False, "note": None}
    pre_sync_snapshot: Dict[str, Any] = {}
    postcheck_report: Optional[Dict[str, Any]] = None
    cleanup_stats: Optional[Dict[str, Any]] = None
    heartbeat_meta: Optional[Dict[str, Any]] = None
    recovery_doc_meta: Optional[Dict[str, Any]] = None
    root_mapper_path: Optional[str] = None
    packages_meta: Optional[Dict[str, Any]] = None
    rebuild_meta: Optional[Dict[str, Any]] = None
    boot_surface: Optional[Dict[str, Any]] = None
    try:
        try:
            populate_esp(mounts.esp, preserve_cmdline=True, preserve_config=True, dry_run=False)
            assert_essentials(mounts.esp)
        except Exception as exc:  # noqa: BLE001
            _emit_result("FAIL_FIRMWARE_CHECK", extra={"error": str(exc)})

        pre_sync_snapshot = _pre_sync_snapshot()
        if flags.skip_rsync:
            rsync_meta.update(
                {
                    "skipped": True,
                    "exit": None,
                    "note": "rsync skipped via --skip-rsync",
                    "summary": {"itemized_sample": [], "counts": {}, "stats": {}},
                    "stats": {},
                    "duration_sec": None,
                }
            )
        else:
            rsync_result = rsync_root(mounts.mnt, dry_run=False, exclude_boot=True)
            rsync_meta = _rsync_meta(rsync_result)
        rsync_meta.setdefault("skipped", False)

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

        try:
            packages_meta = ensure_packages(mounts.mnt)
        except Exception as exc:  # noqa: BLE001
            _emit_result(
                "FAIL_INITRAMFS_VERIFY",
                extra={"phase": "ensure_packages", "error": str(exc)},
            )
        try:
            rebuild_meta = rebuild(mounts.mnt)
        except Exception as exc:  # noqa: BLE001
            _emit_result(
                "FAIL_INITRAMFS_VERIFY",
                extra={"phase": "rebuild", "error": str(exc)},
            )
        write_config(mounts.esp)
        boot_surface = verify_initramfs(mounts.esp, luks_uuid=luks_uuid)
        try:
            boot_surface = require_boot_surface_ok(boot_surface)
        except InitramfsVerificationError as exc:
            _emit_result(
                "FAIL_INITRAMFS_VERIFY",
                extra={"why": exc.why, "checks": exc.result},
            )

        if flags.do_postcheck:
            try:
                heartbeat_meta = install_postboot_heartbeat(mounts.mnt)
                recovery_doc_meta = write_recovery_doc(mounts.mnt, luks_uuid)
                cleanup_stats = cleanup_pycache(mounts.mnt)
                postcheck_report = run_postcheck(mounts.mnt, luks_uuid, p1_uuid)
            except InitramfsVerificationError as exc:
                _emit_result(
                    "FAIL_INITRAMFS_VERIFY",
                    extra={"why": exc.why, "checks": exc.result},
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] postcheck setup failed: {exc}", file=sys.stderr)

    except Exception as exc:  # noqa: BLE001
        print(f"[DIAG] Provisioning error: {exc}", file=sys.stderr)
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
        "log_path": log_path or _result_log_path(),
        "safety_check": safety_snapshot,
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
            "duration_sec": rsync_meta.get("duration_sec"),
            "retries": rsync_meta.get("retries"),
            "stats": rsync_meta.get("stats"),
            "summary": rsync_meta.get("summary"),
        },
        "initramfs": {
            "image": boot_surface.get("initramfs_path") if boot_surface else None,
            "ensure_packages": packages_meta,
            "rebuild": rebuild_meta,
            "verification": boot_surface,
        },
        "postcheck": {
            "requested": flags.do_postcheck,
            "heartbeat": heartbeat_meta,
            "recovery_doc": recovery_doc_meta,
            "report": postcheck_report,
            "cleanup": cleanup_stats,
        },
        "timing": {
            "rsync": {
                "duration_sec": rsync_meta.get("duration_sec"),
                "retries": rsync_meta.get("retries"),
            },
            "ensure_packages": _timing_from_packages(packages_meta),
            "initramfs": _timing_from_rebuild(rebuild_meta),
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


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - exercised via manual CLI
    try:
        return _main_impl(argv)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit_result("FAIL_UNHANDLED", extra={"error": str(exc)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
