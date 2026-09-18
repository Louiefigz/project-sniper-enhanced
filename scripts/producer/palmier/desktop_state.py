"""Lightweight durable state primitives shared by Desktop Palmier hooks."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from palmier.mcp_client import PalmierError
from palmier.timeline_authority import atomic_write_record

STATE_NAME = ".palmier-desktop-authority.json"
POINTER_NAME = ".sniper-palmier-desktop-authority.json"
JOURNAL_NAME = ".palmier-desktop-operations.jsonl"
STATUSES = {"active", "paused", "review-required", "complete"}


@dataclass(frozen=True)
class DesktopStageInput:
    """All immutable inputs bound to one Desktop execution stage."""

    repo: str
    out_dir: str
    plan_path: str
    manifest_path: str
    stage: str
    transcripts_dir: str | None = None
    revision_path: str | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_path(out_dir: str) -> str:
    return os.path.join(out_dir, STATE_NAME)


def pointer_path(repo: str) -> str:
    return os.path.join(repo, POINTER_NAME)


def read_record(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Desktop Palmier {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"Desktop Palmier {label} is malformed")
    return value


def load_state(out_dir: str) -> dict:
    state = read_record(state_path(out_dir), "authority")
    if state.get("schemaVersion") != 1 \
            or state.get("kind") != "palmier-desktop-authority" \
            or state.get("status") not in STATUSES:
        raise PalmierError("Desktop Palmier authority has an unsupported state")
    return state


def load_pointer(repo: str) -> tuple[str, dict]:
    pointer = read_record(pointer_path(repo), "pointer")
    path = pointer.get("authorityPath")
    if pointer.get("schemaVersion") != 1 or not isinstance(path, str) \
            or not os.path.isabs(path) or os.path.islink(path):
        raise PalmierError("Desktop Palmier pointer is malformed")
    state = load_state(os.path.dirname(path))
    if os.path.realpath(path) != os.path.realpath(state_path(state["outDir"])):
        raise PalmierError("Desktop Palmier pointer targets another authority")
    return path, state


def save_state(repo: str, state: dict) -> dict:
    atomic_write_record(state_path(state["outDir"]), state)
    atomic_write_record(pointer_path(repo), {
        "schemaVersion": 1, "authorityPath": state_path(state["outDir"]),
        "outDir": state["outDir"], "updatedAt": now(),
    })
    return state


def append_journal(state: dict, row: dict) -> None:
    with open(state["journalPath"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
