from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_BASE = "/home/admin/rp5"


def _expand(path: str) -> str:
    candidate = Path(path).expanduser()
    try:
        return str(candidate.resolve())
    except FileNotFoundError:
        return str(candidate)


def rp5_base_path() -> str:
    """Return the base directory for RP5 artifacts.

    The location can be overridden via the ``RP5_BASE_PATH`` environment
    variable.  When unset we fall back to the historical ``/home/admin/rp5``
    tree so existing tooling keeps functioning.
    """

    override = os.environ.get("RP5_BASE_PATH")
    if override:
        return _expand(override)
    return _expand(_DEFAULT_BASE)


RP5_BASE_PATH = rp5_base_path()


def rp5_logs_dir() -> str:
    return str(Path(rp5_base_path()) / "03_LOGS")


def rp5_artifacts_dir() -> str:
    return str(Path(rp5_base_path()) / "04_ARTIFACTS")
