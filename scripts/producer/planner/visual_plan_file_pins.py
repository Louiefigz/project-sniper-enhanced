"""Bounded regular-file pins shared by visual-plan admission contracts."""
from __future__ import annotations

import hashlib
import json
import os
import stat

from planner.visual_plan_fields import VisualPlanContractError

MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


def _regular_file_info(path: str, label: str, maximum: int) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise VisualPlanContractError(
            f"{label} file is unavailable: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise VisualPlanContractError(f"{label} must be a regular non-symlink file")
    if info.st_size > maximum:
        raise VisualPlanContractError(f"{label} exceeds the bounded read size")
    return info


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(pin: dict, label: str, maximum: int,
                cache: set[tuple[str, str]] | None = None) -> None:
    """Verify one regular non-symlink file against an exact SHA-256 pin."""
    cache = cache if cache is not None else set()
    path, digest = pin["path"], pin["sha256"]
    key = (path, digest)
    if key in cache:
        return
    _regular_file_info(path, label, maximum)
    if _file_sha256(path) != digest:
        raise VisualPlanContractError(f"{label} SHA-256 does not match file bytes")
    cache.add(key)


def read_json_pin(pin: dict, label: str, maximum: int) -> object:
    """Verify and parse one bounded pinned JSON object."""
    verify_file(pin, label, maximum)
    try:
        with open(pin["path"], "rb") as handle:
            return json.loads(handle.read(maximum + 1))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualPlanContractError(f"{label} is not valid bounded JSON") from exc
