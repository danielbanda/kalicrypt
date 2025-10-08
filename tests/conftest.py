import ast
import sys
import threading
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Set

_ROOT_DIR = Path(__file__).absolute().parent.parent
_PROVISION_DIR = (_ROOT_DIR / "provision").absolute()

_EXECUTED_LINES: Dict[Path, Set[int]] = defaultdict(set)
_CANDIDATE_LINES: Dict[Path, Set[int]] = {}
_PREVIOUS_TRACE = None
_PREVIOUS_THREAD_TRACE = None
_TRACE_ACTIVE = False


def _iter_python_files(directory: Path) -> Iterable[Path]:
    for path in directory.rglob("*.py"):
        if path.is_file():
            yield path.absolute()


def _candidate_lines_for(path: Path) -> Set[int]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return set()

    potential_lines: Set[int] = set()
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        end_lineno = getattr(node, "end_lineno", None)
        if lineno is None:
            continue
        if end_lineno is None:
            end_lineno = lineno
        potential_lines.update(range(lineno, end_lineno + 1))

    lines = set()
    source_lines = source.splitlines()
    for lineno in potential_lines:
        if lineno > len(source_lines):
            continue
        text = source_lines[lineno - 1].strip()
        if not text or text.startswith("#"):
            continue
        lines.add(lineno)
    return lines


for file_path in _iter_python_files(_PROVISION_DIR):
    _CANDIDATE_LINES[file_path] = _candidate_lines_for(file_path)


def _trace(frame, event, arg):
    if event != "line":
        return _trace
    filename = Path(frame.f_code.co_filename)
    try:
        resolved = filename.absolute()
    except OSError:
        return _trace
    if resolved in _CANDIDATE_LINES:
        _EXECUTED_LINES[resolved].add(frame.f_lineno)
    return _trace


def pytest_sessionstart(session):
    global _PREVIOUS_TRACE, _PREVIOUS_THREAD_TRACE, _TRACE_ACTIVE
    if _TRACE_ACTIVE:
        return
    _TRACE_ACTIVE = True
    _EXECUTED_LINES.clear()
    _PREVIOUS_TRACE = sys.gettrace()
    _PREVIOUS_THREAD_TRACE = threading.gettrace()
    sys.settrace(_trace)
    threading.settrace(_trace)


def pytest_sessionfinish(session, exitstatus):
    global _TRACE_ACTIVE
    if not _TRACE_ACTIVE:
        return
    _TRACE_ACTIVE = False

    if _PREVIOUS_TRACE is not None:
        sys.settrace(_PREVIOUS_TRACE)
    else:
        sys.settrace(None)

    threading.settrace(_PREVIOUS_THREAD_TRACE)

    _report_coverage(session)


def _report_coverage(session) -> None:
    if not _CANDIDATE_LINES:
        return

    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    write_line = terminal.write_line if terminal else print

    rows = []
    total_statements = 0
    total_covered = 0

    for path in sorted(_CANDIDATE_LINES):
        candidates = _CANDIDATE_LINES[path]
        if not candidates:
            continue
        executed = _EXECUTED_LINES.get(path, set()) & candidates
        covered = len(executed)
        statements = len(candidates)
        missing = sorted(candidates - executed)
        coverage_pct = (covered / statements * 100.0) if statements else 100.0

        total_statements += statements
        total_covered += covered

        rows.append(
            (
                path.relative_to(_ROOT_DIR),
                statements,
                len(missing),
                coverage_pct,
                missing,
            )
        )

    if not rows:
        return

    write_line("")
    write_line("Coverage summary for 'provision':")
    header = f"{'Name':<60} {'Stmts':>6} {'Miss':>6} {'Cover':>7}"
    write_line(header)
    write_line("-" * len(header))

    for name, statements, missing_count, coverage_pct, missing in rows:
        write_line(
            f"{str(name):<60} {statements:>6} {missing_count:>6} {coverage_pct:>6.1f}%"
        )
        if missing_count:
            preview = ", ".join(map(str, missing[:10]))
            suffix = "..." if missing_count > 10 else ""
            write_line(f"    Missing: {preview}{suffix}")

    if total_statements:
        total_pct = total_covered / total_statements * 100.0
        write_line("-" * len(header))
        write_line(
            f"{'TOTAL':<60} {total_statements:>6} {total_statements - total_covered:>6} {total_pct:>6.1f}%"
        )

