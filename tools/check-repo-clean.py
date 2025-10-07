#!/usr/bin/env python3
import os, sys, json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
banned_dirs = {"__pycache__", "__MACOSX", "05_CHECKPOINTS"}
banned_files = {".DS_Store"}
banned_suffixes = ("~", ".swp", ".orig")
banned_starts = ("._",)

def is_banned(path: pathlib.Path) -> bool:
    parts = set(path.parts)
    if any(d in parts for d in banned_dirs):
        return True
    if path.name in banned_files:
        return True
    if any(path.name.endswith(suf) for suf in banned_suffixes):
        return True
    if any(path.name.startswith(pre) for pre in banned_starts):
        return True
    return False

def scan():
    issues = []
    for p in ROOT.rglob("*"):
        if p.is_dir():
            if p.name in banned_dirs:
                issues.append({"type":"dir","path":str(p.relative_to(ROOT))})
            continue
        if is_banned(p):
            issues.append({"type":"file","path":str(p.relative_to(ROOT))})
    # Duplicate/rogue rules file
    rogue = ROOT / "RP5" / "rules.md"
    if rogue.exists():
        issues.append({"type":"file","path":str(rogue.relative_to(ROOT)), "reason":"duplicate rules; canonical is docs/projects/RP5/rules.md"})
    # Flag removed legacy flags lingering in code/docs
    legacy_flags = [b"--yes", b"", b"", b"--do-postcheck", b"--do-postcheck"]
    flagged = []
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in {".py",".md",".sh",".txt"}:
            try:
                data = p.read_bytes()
            except Exception:
                continue
            for lf in legacy_flags:
                if lf in data:
                    flagged.append((p, lf.decode()))
    for p, lf in flagged:
        issues.append({"type":"legacy-flag","path":str(p.relative_to(ROOT)), "flag":lf})
    return issues

def main():
    issues = scan()
    ok = len(issues) == 0
    out = {"ok": ok, "issues": issues}
    print(json.dumps(out, indent=2))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
