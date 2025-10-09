"""CLI entrypoint for the RP5 NVMe provisioner."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
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
    write_initramfs_conf,
)
from .devices import kill_holders, probe, swapoff_all, uuid_of
from .executil import append_jsonl, resolve_log_path, run, trace, udev_settle
from .firmware import assert_essentials, populate_esp
from .initramfs import (
    InitramfsResolutionError,
    ensure_packages,
    rebuild,
    resolve_initramfs_image,
    verify as verify_initramfs,
    verify_keyfile_in_image,
)
from .luks_lvm import (
    activate_vg,
    close_luks,
    deactivate_vg,
    ensure_keyfile,
    format_luks,
    luks_active_slots,
    make_vg_lv,
    open_luks,
    remove_keyfile_slot,
    remove_passphrase_keyslot,
    test_keyfile_unlock,
)
from .model import Flags, ProvisionPlan
from .mounts import mount_targets_safe, bind_mounts, mount_targets, unmount_all
from .partitioning import apply_layout, guard_not_live_root as partitioning_guard_not_live_root, verify_layout
from .paths import rp5_artifacts_dir, rp5_logs_dir
from .postboot import (
    install_postboot_check as install_postboot_heartbeat,
    remove_postboot_artifacts,
)
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
    "FAIL_KEYFILE_PATH": 2,
    "FAIL_KEYFILE_PERMS": 2,
    "FAIL_REMOVE_PASSPHRASE_BLOCKED": 2,
}

RESULT_LOG_PATH: Optional[str] = None
_LOG_ANNOUNCED = False
CLI_START_MONO = time.perf_counter()
_CURRENT_DEVICE: Optional[str] = None
_SHA_CACHE: Dict[str, Optional[str]] = {}
JSON_OUTPUT_ENABLED = True


def _result_log_path() -> str:
    global RESULT_LOG_PATH
    if RESULT_LOG_PATH:
        return RESULT_LOG_PATH
    path = resolve_log_path()
    if not path:
        base = rp5_logs_dir()
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
        _LOG_ANNOUNCED = True
    return path


def _safety_snapshot(device: str) -> Dict[str, Any]:
    def _capture(cmd: list[str]) -> str:
        try:
            return subprocess.check_output(cmd, text=True).strip()
        except Exception:
            return ""

    root_src = _capture(["findmnt", "-no", "SOURCE", "/"]) or ""
    boot_src = (
            _capture(["findmnt", "-no", "SOURCE", "/boot/firmware"]) or _capture(["findmnt", "-no", "SOURCE", "/boot"]) or ""
    )
    target_pkname = ""
    raw_pk = _capture(["lsblk", "-no", "PKNAME", device])
    if raw_pk:
        target_pkname = raw_pk.splitlines()[0].strip()
    if not target_pkname:
        target_pkname = os.path.basename(device.rstrip("/"))

    disk_pkname = target_pkname
    part_pkname = ""
    part_device = ""
    try:
        dm = probe(device, dry_run=True)
        part_device = dm.p3 or ""
    except Exception:
        part_device = ""

    if part_device:
        part_pk = _capture(["lsblk", "-no", "NAME", part_device]) or ""
        part_pkname = part_pk.splitlines()[0].strip() if part_pk else os.path.basename(part_device.rstrip("/"))
        disk_from_part = _capture(["lsblk", "-no", "PKNAME", part_device]) or ""
        if disk_from_part.strip():
            disk_pkname = disk_from_part.strip()
    if not disk_pkname:
        disk_pkname = os.path.basename(device.rstrip("/"))

    same_disk = _same_underlying_disk(device, root_src)
    snapshot = {
        "root_src": root_src,
        "boot_src": boot_src,
        "target_device": device,
        "target_pkname": target_pkname,
        "disk_pkname": disk_pkname,
        "part_pkname": part_pkname,
        "same_underlying_disk": same_disk,
    }
    return snapshot


def _emit_safety_check(snapshot: Dict[str, Any]) -> None:
    payload = {"ts": int(time.time()), "event": "SAFETY_CHECK", **snapshot}
    append_jsonl(_result_log_path(), payload)
    try:
        trace("cli.safety_check", **snapshot)
    except Exception:
        pass


def _log_path(name: str) -> str:
    base = rp5_logs_dir()
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(base, f"{name}_{ts}.json")


def _git_rev_parse(ref: str) -> str | None:
    if ref in _SHA_CACHE:
        return _SHA_CACHE[ref]
    try:
        proc = subprocess.run(
            ["git", "rev-parse", ref],
            capture_output=True,
            text=True,
            check=True,
        )
        value = proc.stdout.strip()
    except Exception:
        value = None
    _SHA_CACHE[ref] = value
    return value


def _git_current_branch() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch = proc.stdout.strip()
        return branch or None
    except Exception:
        return None


def _version_metadata() -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    branch = _git_current_branch() or "in-mem"
    return {
        "sha_main": _git_rev_parse("HEAD"),
        "sha_cli": _git_rev_parse("HEAD:provision/cli.py"),
        "ts_utc": ts,
        "branch": branch,
        "log_path": _result_log_path(),
    }


def _emit_version_stamp(meta: Dict[str, Any]) -> Dict[str, Any]:
    base = rp5_logs_dir()
    os.makedirs(base, exist_ok=True)
    ts = meta.get("ts_utc") or meta.get("ts")
    if not ts:
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        meta = dict(meta)
        meta["ts_utc"] = ts
    path = os.path.join(base, f"{ts}.ver")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
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
    log_path = payload.get("log_path") or _result_log_path()
    if log_path:
        payload.setdefault("log_path", log_path)
    meta = _version_metadata()
    version_meta = meta
    if not kind.endswith("_OK"):
        version_meta = _emit_version_stamp(dict(meta))
        payload["version"] = version_meta
    append_jsonl(_result_log_path(), payload)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    sha_cli = (version_meta.get("sha_cli") or "")[:7] if isinstance(version_meta, dict) else ""
    sha_main = (version_meta.get("sha_main") or "")[:7] if isinstance(version_meta, dict) else ""
    why_text = str(payload.get("why") or payload.get("reason") or "")
    device = payload.get("device") or _CURRENT_DEVICE or ""
    total_ms = int(max(0.0, (time.perf_counter() - CLI_START_MONO) * 1000))
    final_log_path = payload.get("log_path") or _result_log_path() or ""
    final_line = (
        f"result={kind} why={why_text} device={device} timing_total_ms={total_ms} "
        f"log_path={final_log_path} sha_cli={sha_cli} sha_main={sha_main}"
    )
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
        run(["findmnt", "-R", "/mnt/nvme"], check=False)
    except Exception:
        pass
    try:
        run(["lsblk", "-f"], check=False)
    except Exception:
        pass
    try:
        run(["mount"], check=False)
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
    steps.append("write fstab/crypttab/cmdline + assert UUIDs")
    if flags.keyfile_auto:
        steps.append("install_keyfile()/luksAddKey()")
    steps.append("ensure_packages()/rebuild()/verify_initramfs()")
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
    root_mapper = dm.root_lv_path or f"/dev/mapper/{dm.vg}-{dm.lv}"
    device_map = dict(vars(dm))
    device_map["root_lv_path"] = root_mapper
    plan_block = {
        "device": plan.device,
        "esp_mb": plan.esp_mb,
        "boot_mb": plan.boot_mb,
        "passphrase_file": plan.passphrase_file,
        "device_map": device_map,
        "detected": {
            "vg": dm.vg,
            "lv": dm.lv,
            "root_lv_path": root_mapper,
            "root_mapper": root_mapper,
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
        "initramfs": {"image": None}, "postcheck": {
            "requested": flags.do_postcheck,
            **({"offer": "--do-postcheck"} if not flags.do_postcheck else {}),
        },
        "safety_check": safety_snapshot,
        "timestamp": int(time.time()),
        "key_unlock":
            (
                {"mode": "keyfile", "path": flags.keyfile_path}
                if flags.keyfile_auto
                else {"mode": "prompt", "path": None}
            )}
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
    summary_stats = summary.setdefault("stats", {})
    for key, value in stats.items():
        summary_stats.setdefault(key, value)
    meta["summary"] = summary
    meta["stats"] = stats
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
    parser.add_argument("--keyfile-auto", action="store_true")
    parser.add_argument("--keyfile-path", default="/etc/cryptsetup-keys.d/cryptroot.key")
    parser.add_argument("--keyfile-rotate", action="store_true")
    parser.add_argument("--remove-passphrase", action="store_true")
    parser.add_argument("--json", dest="json", action="store_true", default=True)
    parser.add_argument("--no-json", dest="json", action="store_false")
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


_KEYFILE_ROOT = "/etc/cryptsetup-keys.d"


def _normalize_keyfile_path(path: Optional[str]) -> Optional[str]:
    if path is None:
        return None
    normalized = os.path.normpath(path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized.lstrip("/")
    return normalized


def _require_keyfile_path(path: str) -> str:
    normalized = _normalize_keyfile_path(path)
    if not normalized:
        _emit_result(
            "FAIL_KEYFILE_PATH",
            extra={"hint": "keyfile path must be provided when --keyfile-auto is set"},
        )
    allowed_root = os.path.normpath(_KEYFILE_ROOT)
    candidate = os.path.normpath(normalized)
    if not candidate.startswith(allowed_root + os.sep) and candidate != allowed_root:
        _emit_result(
            "FAIL_KEYFILE_PATH",
            extra={
                "path": path,
                "hint": "keyfile path must reside under /etc/cryptsetup-keys.d",
            },
        )
    if candidate == allowed_root:
        _emit_result(
            "FAIL_KEYFILE_PATH",
            extra={
                "path": path,
                "hint": "keyfile path must include a filename under /etc/cryptsetup-keys.d",
            },
        )
    return candidate


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


def _backup_existing_keyfile(mnt: str, keyfile_path: str) -> Optional[str]:
    rel = keyfile_path.lstrip("/")
    host_path = os.path.normpath(os.path.join(mnt, rel))
    if not os.path.isfile(host_path):
        return None
    try:
        with open(host_path, "rb") as src:
            data = src.read()
        if not data:
            return None
        with tempfile.NamedTemporaryFile(prefix="rp5-key-rotate-", dir="/tmp", delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            os.fchmod(tmp.fileno(), 0o600)
            return tmp.name
    except Exception:
        return None


def _run_postcheck_only(
        plan: ProvisionPlan,
        flags: Flags,
        passphrase_file: str,
        safety_snapshot: Dict[str, Any],
        log_path: Optional[str],
) -> None:  # pragma: no cover - hardware flow
    dm = probe(plan.device)
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

        rec_dir = os.path.join(rp5_artifacts_dir(), "recovery")
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
    global JSON_OUTPUT_ENABLED
    JSON_OUTPUT_ENABLED = bool(getattr(args, "json", True))
    mode = "plan" if args.plan else ("dry" if args.dry_run else "full")
    sync_performed = not args.skip_rsync

    log_path = _announce_log_path()

    global _CURRENT_DEVICE
    _CURRENT_DEVICE = args.device

    keyfile_auto_flag = bool(args.keyfile_auto or args.keyfile_rotate or args.remove_passphrase)

    keyfile_path = _normalize_keyfile_path(args.keyfile_path) or "/etc/cryptsetup-keys.d/cryptroot.key"
    if keyfile_auto_flag:
        keyfile_path = _require_keyfile_path(keyfile_path)

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
            keyfile_auto=keyfile_auto_flag,
            keyfile_path=keyfile_path,
            keyfile_rotate=args.keyfile_rotate,
            remove_passphrase=args.remove_passphrase,
        )
    except Exception:
        pass

    if args.remove_passphrase:
        print(
            "[WARN] --remove-passphrase will remove the interactive LUKS passphrase slot after keyfile verification.",
            file=sys.stderr,
        )

    flags = Flags(
        plan=args.plan,
        dry_run=args.dry_run,
        skip_rsync=args.skip_rsync,
        do_postcheck=args.do_postcheck,
        tpm_keyscript=args.tpm_keyscript,
        assume_yes=args.assume_yes,
        keyfile_auto=keyfile_auto_flag,
        keyfile_path=keyfile_path,
        keyfile_rotate=args.keyfile_rotate,
        remove_passphrase=args.remove_passphrase,
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
    same_disk = safety_snapshot.get("same_underlying_disk")
    if same_disk is None:
        same_disk = _same_underlying_disk(plan.device, safety_snapshot.get("root_src", ""))
    same_disk = bool(same_disk)
    _emit_safety_check(safety_snapshot)

    ok, reason = safety.guard_not_live_disk(plan.device)
    try:
        partitioning_guard_not_live_root(plan.device)
    except SystemExit as exc:
        extra = dict(safety_snapshot)
        reason_text = exc.code if isinstance(exc.code, str) else str(exc)
        extra["reason"] = reason_text or "live disk guard triggered"
        _emit_result("FAIL_LIVE_DISK_GUARD", extra=extra)
    if not ok:
        extra = dict(safety_snapshot)
        extra["reason"] = reason or "live disk guard triggered"
        _emit_result("FAIL_LIVE_DISK_GUARD", extra=extra)

    root_src = safety_snapshot.get("root_src", "")
    if same_disk:
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

    probe(plan.device)

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

    initramfs_image_path: Optional[str] = None
    rsync_meta: Dict[str, Any] = {"exit": 0, "err": None, "out": None, "warning": False, "note": None}
    postcheck_report: Optional[Dict[str, Any]] = None
    cleanup_stats: Optional[Dict[str, Any]] = None
    heartbeat_meta: Optional[Dict[str, Any]] = None
    recovery_doc_meta: Optional[Dict[str, Any]] = None
    packages_meta: Optional[Dict[str, Any]] = None
    rebuild_meta: Optional[Dict[str, Any]] = None
    boot_surface: Optional[Dict[str, Any]] = None
    postcheck_pruned: Optional[Dict[str, Any]] = None
    keyfile_meta: Optional[Dict[str, Any]] = None
    key_rotation_meta: Optional[Dict[str, Any]] = None
    key_unlock_verified = False
    initramfs_key_meta: Optional[Dict[str, Any]] = None
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
                    "summary": {"itemized_sample": [], "counts": {}, "stats": {}, "numbers_block": []},
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
        try:
            write_crypttab(
                mounts.mnt,
                luks_uuid,
                passphrase_file,
                keyscript_path=None,
                keyfile_path=flags.keyfile_path if flags.keyfile_auto else None,
                enable_keyfile=flags.keyfile_auto,
            )
        except ValueError as exc:
            _emit_result(
                "FAIL_KEYFILE_PATH",
                extra={"path": flags.keyfile_path, "error": str(exc)},
            )
        assert_crypttab_uuid(mounts.mnt, luks_uuid)
        if flags.keyfile_auto:
            try:
                # write_initramfs_conf(mounts.mnt)
                adawd = 1 + 1
            except Exception as exc:  # noqa: BLE001
                _emit_result(
                    "FAIL_INITRAMFS_VERIFY",
                    extra={"phase": "initramfs_conf", "error": str(exc)},
                )
        root_mapper_path = dm.root_lv_path or f"/dev/mapper/{dm.vg}-{dm.lv}"
        write_cmdline(
            mounts.esp,
            luks_uuid,
            root_mapper=root_mapper_path,
            vg=dm.vg,
            lv=dm.lv,
        )
        assert_cmdline_uuid(mounts.esp, luks_uuid, root_mapper=root_mapper_path)

        # if flags.keyfile_auto:
        #     key_slots_before: set[int] = set()
        #     try:
        #         key_slots_before = luks_active_slots(dm.p3)
        #     except Exception:
        #         key_slots_before = set()
        #     old_key_backup = _backup_existing_keyfile(mounts.mnt, flags.keyfile_path) if flags.keyfile_rotate else None
        #     try:
        #         keyfile_meta = ensure_keyfile(
        #             mounts.mnt,
        #             flags.keyfile_path,
        #             dm.p3,
        #             passphrase_file,
        #             rotate=flags.keyfile_rotate,
        #         )
        #     except PermissionError as exc:
        #         if old_key_backup:
        #             try:
        #                 os.remove(old_key_backup)
        #             except Exception:
        #                 pass
        #         _emit_result(
        #             "FAIL_KEYFILE_PERMS",
        #             extra={"path": flags.keyfile_path, "error": str(exc)},
        #         )
        #     except ValueError as exc:
        #         if old_key_backup:
        #             try:
        #                 os.remove(old_key_backup)
        #             except Exception:
        #                 pass
        #         _emit_result(
        #             "FAIL_KEYFILE_PATH",
        #             extra={"path": flags.keyfile_path, "error": str(exc)},
        #         )
        #     except Exception as exc:  # noqa: BLE001
        #         if old_key_backup:
        #             try:
        #                 os.remove(old_key_backup)
        #             except Exception:
        #                 pass
        #         _emit_result(
        #             "FAIL_LUKS",
        #             extra={"phase": "luksAddKey", "error": str(exc)},
        #         )
        # 
        #     key_slots_after: set[int] = set()
        #     try:
        #         key_slots_after = luks_active_slots(dm.p3)
        #     except Exception:
        #         key_slots_after = set(key_slots_before)
        # 
        #     if keyfile_meta is not None:
        #         keyfile_meta["slots_before"] = sorted(key_slots_before)
        #         keyfile_meta["slots_after"] = sorted(key_slots_after)
        #         added = sorted(key_slots_after - key_slots_before)
        #         if added and not keyfile_meta.get("slot"):
        #             keyfile_meta["slot"] = added[-1]
        # 
        #     keyfile_host_path = keyfile_meta.get("host_path") if isinstance(keyfile_meta, dict) else None
        #     if keyfile_host_path:
        #         try:
        #             key_unlock_verified = test_keyfile_unlock(dm.p3, keyfile_host_path)
        #         except Exception:
        #             key_unlock_verified = False
        #         if keyfile_meta is not None:
        #             keyfile_meta["unlock_test_after"] = key_unlock_verified
        # 
        #     if flags.keyfile_rotate:
        #         new_slot = keyfile_meta.get("slot") if isinstance(keyfile_meta, dict) else None
        #         old_slot_index = None
        #         if not key_unlock_verified:
        #             if old_key_backup:
        #                 try:
        #                     os.remove(old_key_backup)
        #                 except Exception:
        #                     pass
        #             _emit_result(
        #                 "FAIL_LUKS",
        #                 extra={"phase": "keyfile_rotate", "why": "new keyfile failed --test-passphrase"},
        #             )
        #         if old_key_backup:
        #             try:
        #                 before_remove = set(key_slots_after) if key_slots_after else luks_active_slots(dm.p3)
        #                 remove_keyfile_slot(dm.p3, old_key_backup)
        #                 after_remove = luks_active_slots(dm.p3)
        #                 removed_slots = sorted(before_remove - after_remove)
        #                 if removed_slots:
        #                     old_slot_index = removed_slots[0]
        #                 key_slots_after = after_remove
        #             except Exception as exc:
        #                 try:
        #                     os.remove(old_key_backup)
        #                 except Exception:
        #                     pass
        #                 _emit_result(
        #                     "FAIL_LUKS",
        #                     extra={"phase": "keyfile_rotate_remove", "error": str(exc)},
        #                 )
        #             else:
        #                 try:
        #                     os.remove(old_key_backup)
        #                 except Exception:
        #                     pass
        #         if keyfile_meta is not None:
        #             keyfile_meta["slots_after"] = sorted(key_slots_after)
        #         key_rotation_meta = {"old_slot": old_slot_index, "new_slot": new_slot}

        try:
            initramfs_image_path = resolve_initramfs_image(mounts.esp)
        except InitramfsResolutionError as exc:
            _emit_result(
                "FAIL_INITRAMFS_PATH",
                extra={
                    "boot_fw": mounts.esp,
                    "config_path": exc.config_path,
                    "snippet": exc.snippet,
                },
            )
        try:
            packages_meta = ensure_packages(mounts.mnt)
        except Exception as exc:  # noqa: BLE001
            _emit_result(
                "FAIL_INITRAMFS_VERIFY",
                extra={"phase": "ensure_packages", "error": str(exc)},
            )
        try:
            rebuild_target = initramfs_image_path or mounts.mnt
            rebuild_meta = rebuild(rebuild_target, force_prompt=not flags.keyfile_auto)
        except Exception as exc:  # noqa: BLE001
            _emit_result(
                "FAIL_INITRAMFS_VERIFY",
                extra={"phase": "rebuild", "error": str(exc)},
            )
        # if flags.keyfile_auto:
        #     expected_key_entry = "etc/cryptsetup-keys.d/cryptroot.key"
        #     verify_target = initramfs_image_path or mounts.esp
        #     initramfs_key_meta = verify_keyfile_in_image(verify_target, f"/{expected_key_entry}")
        #     if initramfs_key_meta is not None:
        #         initramfs_key_meta["expected"] = expected_key_entry
        #     if not initramfs_key_meta.get("included"):
        #         _emit_result(
        #             "FAIL_INITRAMFS_VERIFY",
        #             extra={
        #                 "image": initramfs_key_meta.get("image") or verify_target,
        #                 "expected": expected_key_entry,
        #             },
        #         )
        # image_basename = os.path.basename(initramfs_image_path) if initramfs_image_path else "initramfs_2712"
        # write_config(mounts.esp, initramfs_image=image_basename)
        # boot_surface = verify_initramfs(mounts.esp, luks_uuid=luks_uuid)
        # try:
        #     boot_surface = require_boot_surface_ok(boot_surface)
        # except InitramfsVerificationError as exc:
        #     _emit_result(
        #         "FAIL_INITRAMFS_VERIFY",
        #         extra={"why": exc.why, "checks": exc.result},
        #     )
        # 
        # if flags.remove_passphrase:
        #     keyfile_in_initramfs = bool(initramfs_key_meta and initramfs_key_meta.get("included"))
        #     prerequisites_ok = bool(
        #         flags.keyfile_auto and keyfile_meta and keyfile_in_initramfs and key_unlock_verified
        #     )
        #     if not prerequisites_ok:
        #         why = "keyfile prerequisites not met"
        #         if not keyfile_meta:
        #             why = "keyfile metadata missing"
        #         elif not keyfile_in_initramfs:
        #             why = "initramfs missing embedded keyfile"
        #         elif not key_unlock_verified:
        #             why = "keyfile unlock test failed"
        #         _emit_result(
        #             "FAIL_REMOVE_PASSPHRASE_BLOCKED",
        #             extra={
        #                 "why": why,
        #                 "key_unlock_verified": key_unlock_verified,
        #                 "initramfs_has_key": keyfile_in_initramfs,
        #             },
        #         )
        #     try:
        #         remove_passphrase_keyslot(dm.p3, passphrase_file)
        #     except Exception as exc:  # noqa: BLE001
        #         _emit_result(
        #             "FAIL_SAFETY_GUARD",
        #             extra={
        #                 "why": "failed to remove LUKS passphrase", "error": str(exc)
        #             },
        #         )

        postcheck_pruned = remove_postboot_artifacts(mounts.mnt)

        if flags.do_postcheck:
            try:
                heartbeat_meta = install_postboot_heartbeat(mounts.mnt)
                recovery_doc_meta = write_recovery_doc(mounts.mnt, luks_uuid)
                cleanup_stats = cleanup_pycache(mounts.mnt)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] postcheck setup failed: {exc}", file=sys.stderr)
            try:
                postcheck_report = run_postcheck(
                    mounts.mnt,
                    luks_uuid,
                    p1_uuid,
                    keyfile_path=flags.keyfile_path if flags.keyfile_auto else None,
                    initramfs_key_meta=initramfs_key_meta,
                )
            except InitramfsVerificationError as exc:
                _emit_result(
                    "FAIL_INITRAMFS_VERIFY",
                    extra={"why": exc.why, "checks": exc.result},
                )
            except Exception as exc:  # noqa: BLE001
                _emit_result(
                    "FAIL_POSTCHECK",
                    extra={"error": str(exc)},
                )

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

    initramfs_block = {
        "image": boot_surface.get("initramfs_path") if boot_surface else None,
        "resolved_image": initramfs_image_path,
        "ensure_packages": packages_meta,
        "rebuild": rebuild_meta,
        "verification": boot_surface,
        "keyfile": bool(flags.keyfile_auto),
        "keyfile_included": bool(initramfs_key_meta.get("included")) if initramfs_key_meta else False,
        "keyfile_name": initramfs_key_meta.get("basename") if initramfs_key_meta else None,
    }
    if initramfs_key_meta:
        initramfs_block["keyfile_meta"] = initramfs_key_meta

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
            "root_lv_path": root_mapper_path,
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
        "initramfs": initramfs_block,
        "postcheck": {
            "requested": flags.do_postcheck,
            "heartbeat": heartbeat_meta,
            "recovery_doc": recovery_doc_meta,
            "report": postcheck_report,
            "cleanup": cleanup_stats,
            "pruned": postcheck_pruned,
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
        "same_underlying_disk": same_disk,
        "device": plan.device,
        "keyfile": keyfile_meta
    }
    if key_rotation_meta:
        result_payload["key_rotation"] = key_rotation_meta
    if flags.keyfile_auto:
        result_payload["security_caveat"] = "embedded_key_in_initramfs"
    result_payload["key_unlock"] = (
        {"mode": "keyfile", "path": flags.keyfile_path}
        if flags.keyfile_auto
        else {"mode": "prompt", "path": None}
    )
    if not flags.do_postcheck:
        result_payload["postcheck"]["offer"] = "--do-postcheck"
        result_payload.setdefault("timing", {})["total_ms"] = int(max(0.0, (time.perf_counter() - CLI_START_MONO) * 1000))
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
