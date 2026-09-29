"""Exact process identities for conformance probes.

A probe records PID, start time and process group while the tree it launched is
intact, then judges liveness only by that exact identity. After a parent dies its
children are reparented to launchd, so ancestry cannot be rediscovered later.
Signals go only to identities the probe itself recorded.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

from native_render_processes import ProcessIdentity, identity_matches, process_table

PS = "/bin/ps"


@dataclass(frozen=True)
class ArgvSearch:
    """Find one descendant of an exact root whose argv equals an accepted shape."""

    root: ProcessIdentity
    shapes: tuple[tuple[str, ...], ...]
    timeout_s: float = 15.0


def table() -> dict[int, tuple[int, int, str]]:
    """Return PID -> (PPID, PGID, lstart) for every process on the host."""
    out = subprocess.run([PS, "-axo", "pid=,ppid=,pgid=,lstart="],
                         capture_output=True, text=True, check=True).stdout
    return process_table(out)


def commands() -> dict[int, tuple[str, ...]]:
    """Return PID -> whitespace-split argv as ps reports it (never truncated)."""
    out = subprocess.run([PS, "-axww", "-o", "pid=,command="],
                         capture_output=True, text=True, check=True).stdout
    rows = {}
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit():
            rows[int(parts[0])] = tuple(parts[1:])
    return rows


def identity_of(pid: int) -> ProcessIdentity | None:
    """Pin a live PID to its current start time and process group."""
    row = table().get(pid)
    return None if row is None else ProcessIdentity(pid=pid, started=row[2], pgid=row[1])


def alive(identity: ProcessIdentity | None) -> bool:
    """True only while the exact recorded identity still exists."""
    return identity is not None and identity_matches(table(), identity)


def descendants(root: ProcessIdentity, rows: dict) -> set[int]:
    """Every process currently below an exact root, root excluded."""
    if not identity_matches(rows, root):
        return set()
    owned = {root.pid}
    while True:
        grown = owned | {pid for pid, row in rows.items() if row[0] in owned}
        if grown == owned:
            return owned - {root.pid}
        owned = grown


def tree(root: ProcessIdentity) -> list[dict]:
    """Evidence rows for the live tree below a root: pid, ppid, pgid and argv."""
    rows, argv = table(), commands()
    found = sorted(descendants(root, rows))
    return [{"pid": pid, "ppid": rows[pid][0], "pgid": rows[pid][1],
             "argv": list(argv.get(pid, ()))[:6]} for pid in found]


def _scan(search: ArgvSearch) -> ProcessIdentity | None:
    """One pass over the current tree below the root for an accepted argv."""
    rows, argv = table(), commands()
    matches = [pid for pid in sorted(descendants(search.root, rows)) if argv.get(pid) in search.shapes]
    if not matches:
        return None
    return ProcessIdentity(pid=matches[0], started=rows[matches[0]][2], pgid=rows[matches[0]][1])


def find_descendant(search: ArgvSearch) -> ProcessIdentity | None:
    """Poll until a descendant with an accepted argv appears, or time out."""
    deadline = time.monotonic() + search.timeout_s
    found = _scan(search)
    while found is None and time.monotonic() < deadline:
        time.sleep(0.25)
        found = _scan(search)
    return found


def signal_exact(identity: ProcessIdentity | None, sig: int) -> bool:
    """Signal a recorded identity only while it still matches; report whether sent."""
    if not alive(identity):
        return False
    os.kill(identity.pid, sig)
    return True


def wait_gone(identity: ProcessIdentity | None, timeout_s: float) -> float | None:
    """Seconds until the identity disappeared, or None if it outlived the window."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        if not alive(identity):
            return round(time.monotonic() - start, 3)
        time.sleep(0.2)
    return None


def as_dict(identity: ProcessIdentity | None) -> dict | None:
    """Serializable identity for evidence files."""
    return None if identity is None else vars(identity).copy()
