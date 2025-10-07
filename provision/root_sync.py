
"""Root filesystem sync to target (Phase 5.2)."""
import shutil
from .executil import run


def _parse_rsync_stats(text: str) -> dict:
    if not isinstance(text, str): 
        return {}
    stats = {}
    for line in text.splitlines():
        line = line.strip()
        if not line: 
            continue
        # Simple, robust parses
        if line.lower().startswith("number of files transferred:"):
            try: stats["files_transferred"] = int(line.split(":")[1].strip().replace(",",""))
            except: pass
        elif line.lower().startswith("total file size:"):
            stats["total_file_size"] = line.split(":",1)[1].strip()
        elif line.lower().startswith("total transferred file size:"):
            stats["transferred_size"] = line.split(":",1)[1].strip()
        elif line.lower().startswith("literal data:"):
            stats["literal_data"] = line.split(":",1)[1].strip()
        elif line.lower().startswith("matched data:"):
            stats["matched_data"] = line.split(":",1)[1].strip()
        elif line.lower().startswith("file list size:"):
            stats["file_list_size"] = line.split(":",1)[1].strip()
        elif line.lower().startswith("total bytes sent:"):
            stats["bytes_sent"] = line.split(":",1)[1].strip()
        elif line.lower().startswith("total bytes received:"):
            stats["bytes_received"] = line.split(":",1)[1].strip()
        elif line.lower().startswith("sent ") and " bytes  received " in line and " bytes/sec" in line:
            stats["throughput_line"] = line
        elif line.lower().startswith("speedup is "):
            stats["speedup"] = line.split(" ",2)[2].strip()
    return stats

EXCLUDES = ["/proc", "/sys", "/dev", "/run", "/mnt", "/media", "/tmp"]

def rsync_root(dst_mnt: str, dry_run: bool=False, timeout_sec: int = 7200, exclude_boot: bool = False):
    if shutil.which("rsync"):
        base = ["rsync","-aHAXx","--numeric-ids","--delete-after","--info=progress2", "--stats", "--itemize-changes"]
        for e in EXCLUDES:
            base += ["--exclude", e]
        cmd = base + ["/", dst_mnt + "/"]
        import subprocess
    try:
        return run(cmd, check=True, dry_run=dry_run, timeout=timeout_sec)
    except subprocess.CalledProcessError as e:
        if e.returncode in (23, 24):
            print(f"[WARN] rsync completed with return code {e.returncode} (partial transfer/vanished files). Continuing.")
            return e
        raise
    # Fallback: cp -a (no delete, best effort)
    return run(["cp","-a","/.", dst_mnt], check=True, dry_run=dry_run, timeout=timeout_sec)


# RSYNC_FALLBACK_OK helper
def _rsync_with_fallback(run, cmd, src, dst):
    import subprocess, shutil, os
    try:
        rc = subprocess.run(cmd, capture_output=True, text=True).returncode
        if rc in (0, 23, 24):
            return True
    except Exception:
        pass
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return True
