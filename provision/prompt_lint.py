#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

BANNED = {
    "ensure", "crucial", "vital", "nestled", "uncover", "journey", "embark", "unleash", "dive",
    "realm", "discover", "delve", "plethora", "whether", "indulge", "more than just", "not just",
    "look no further", "landscape", "navigate", "daunting", "both style", "tapestry", "unique blend",
    "blend", "enhancing", "game changer", "stand out", "stark", "contrast"
}


def is_text(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".mdx", ".txt", ".rst", ".ini", ".conf", ".cfg"}


def scan_file(p: Path, required_sections):
    text = p.read_text(encoding="utf-8", errors="ignore")
    issues = []
    # banned
    low = text.lower()
    for phrase in BANNED:
        if phrase in low:
            issues.append(f"BANNED: '{phrase}'")
    # sections
    for sec in required_sections:
        if sec.lower() not in low:
            issues.append(f"MISSING SECTION: '{sec}'")
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Root folder to scan")
    ap.add_argument("--sections", default="", help="Comma-separated required section names")
    args = ap.parse_args()

    required_sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    root = Path(args.root)

    problems = {}
    for path in root.rglob("*"):
        if path.is_file() and is_text(path):
            iss = scan_file(path, required_sections)
            if iss:
                problems[str(path)] = iss

    if not problems:
        print("[OK] No issues found.")
        sys.exit(0)

    print("[REPORT] Issues found:")
    for f, iss in sorted(problems.items()):
        print(f"  - {f}")
        for i in iss:
            print(f"      * {i}")
    sys.exit(1)


if __name__ == "__main__":
    main()
