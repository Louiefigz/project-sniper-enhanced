"""Read-only identity selection for native render processes, including orphans.

The supervisor must build its registry from verified live ancestry. This module
does not treat an arbitrary registry as authority to signal a process.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


class ResourceMeasurementError(RuntimeError):
    """A required live resource measurement is unavailable or malformed."""


@dataclass(frozen=True)
class ProcessIdentity:
    """Expected identity; omitted start or group makes observation unbound."""

    pid: int
    started: str | None = None
    pgid: int | None = None


class MissingProcessFootprint(ResourceMeasurementError):
    """Keep exact unmeasured live identities while preserving retry compatibility."""

    def __init__(self, identities: tuple[ProcessIdentity, ...],
                 reason: str = "missing-memory-row") -> None:
        """Record observed PID/start/group values without assuming process exit."""
        self.identities = identities
        self.reason = reason
        self.evidence = {"reason": reason, "identities": [vars(row) for row in identities]}
        super().__init__("Owned process footprint missing; resample tree")


@dataclass(frozen=True)
class ProcessFootprint:
    """Live identity and memory; MEM already includes the compressed footprint."""

    pid: int
    parent_pid: int
    pgid: int
    started: str
    footprint_bytes: int
    compressed_bytes: int


@dataclass(frozen=True)
class ProcessRequest:
    """A live discovery root and identities previously recorded by its owner."""

    root: ProcessIdentity | None = None
    remembered: tuple[ProcessIdentity, ...] = ()


def parse_size(value: str) -> int:
    """Parse macOS top sizes without treating unknown units as healthy zeros."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([BKMGT])(?:[+-])?", value.strip())
    if not match:
        raise ResourceMeasurementError(f"Unrecognized memory size: {value!r}")
    return int(float(match[1]) * 1024 ** "BKMGT".index(match[2]))


def process_table(text: str) -> dict[int, tuple[int, int, str]]:
    """Parse PID, PPID, PGID and exact lstart from the current process table."""
    table = {}
    pattern = r"[ \t]*(\d+)[ \t]+(\d+)[ \t]+(\d+)[ \t]+(\S[^\n]*)"
    for line in text.splitlines():
        if not line.strip():
            continue
        row = re.fullmatch(pattern, line)
        if row is None:
            raise ResourceMeasurementError("Malformed nonempty process-table row")
        pid, parent, group = (int(row[index]) for index in (1, 2, 3))
        if pid in table:
            raise ResourceMeasurementError("Duplicate PID in process table")
        table[pid] = (parent, group, row[4].strip())
    if not table:
        raise ResourceMeasurementError("Process table is unavailable or has an unexpected format")
    return table


def identity_matches(table: dict, identity: ProcessIdentity) -> bool:
    """Require PID, start and group to match before considering lifecycle work."""
    row = table.get(identity.pid)
    return (row is not None and identity.started is not None and identity.pgid is not None
            and row[1] == identity.pgid and row[2] == identity.started)


def _anchors(table: dict, request: ProcessRequest) -> tuple[set[int], list[int], list[int], bool]:
    """Select matched identities, excluding recycled PIDs and unrelated groups."""
    anchors, missing, reused = set(), [], []
    identities = request.remembered + ((request.root,) if request.root else ())
    verified = bool(identities)
    for identity in identities:
        if isinstance(identity.pid, bool) or not isinstance(identity.pid, int) or identity.pid <= 1:
            raise ValueError("Owned root must be an explicit positive render PID")
        if identity.pid not in table:
            missing.append(identity.pid)
            continue
        if identity.started is None or identity.pgid is None:
            anchors.add(identity.pid)
            verified = False
            continue
        if identity_matches(table, identity):
            anchors.add(identity.pid)
        else:
            reused.append(identity.pid)
    return anchors, sorted(set(missing)), sorted(set(reused)), verified


def _descendants(table: dict, owned: set[int]) -> set[int]:
    """Expand verified anchors through the observed parent relationships."""
    while True:
        expanded = owned | {pid for pid, row in table.items() if row[0] in owned}
        if expanded == owned:
            return owned
        owned = expanded


def reconcile_process_request(before_text: str, after_text: str,
                              request: ProcessRequest) -> ProcessRequest:
    """Retain observed orphans and reject live identities unbound across top."""
    table = process_table(before_text)
    anchors, _, _, _ = _anchors(table, request)
    observed = _descendants(table, anchors)
    remembered = {(row.pid, row.started, row.pgid): row for row in request.remembered}
    for pid in sorted(observed):
        identity = ProcessIdentity(pid, table[pid][2], table[pid][1])
        remembered.setdefault((pid, identity.started, identity.pgid), identity)
    result = ProcessRequest(request.root, tuple(remembered.values()))
    after = process_table(after_text)
    anchors, _, _, _ = _anchors(after, result)
    live = _descendants(after, anchors)
    identities = tuple(ProcessIdentity(pid, after[pid][2], after[pid][1])
                       for pid in sorted(live))
    unbound = tuple(row for row in identities if not identity_matches(table, row))
    if unbound:
        raise MissingProcessFootprint(unbound, "identity-not-stable-across-footprint-read")
    return result


def select_processes(ps_text: str, top: str, request: ProcessRequest) -> dict:
    """Include remembered detached children even after their parent exits."""
    table = process_table(ps_text)
    anchors, missing, reused, verified = _anchors(table, request)
    owned = _descendants(table, anchors)
    rows = re.findall(r"(?m)^\s*(\d+)\s+(\S+)\s+(\S+)\s*$", top)
    found = {int(pid): (parse_size(mem), parse_size(compressed)) for pid, mem, compressed in rows
             if int(pid) in owned}
    if set(found) != owned:
        identities = tuple(ProcessIdentity(pid, table[pid][2], table[pid][1])
                           for pid in sorted(owned - set(found)))
        raise MissingProcessFootprint(identities)
    processes = tuple(ProcessFootprint(pid, *table[pid], *found[pid]) for pid in sorted(owned))
    return {"processes": processes, "missing": tuple(missing), "reused": tuple(reused),
            "verified": verified and not reused}


def read_identities(path: Path) -> tuple[ProcessIdentity, ...]:
    """Read a bounded owner registry of explicit PID, start-time and PGID pins."""
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Process identity registry exceeds one MiB")
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError("Process identity registry must be a bounded list")
    identities = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"pid", "started", "pgid"}:
            raise ValueError("Registry rows require exactly pid, started and pgid")
        identity = ProcessIdentity(**row)
        valid_numbers = all(type(x) is int and x > 1 for x in (identity.pid, identity.pgid))
        if not valid_numbers or not isinstance(identity.started, str) or not identity.started.strip():
            raise ValueError("Registry identities must include positive IDs and exact lstart")
        identities.append(identity)
    if len({identity.pid for identity in identities}) != len(identities):
        raise ValueError("Duplicate PID in process identity registry")
    return tuple(identities)
