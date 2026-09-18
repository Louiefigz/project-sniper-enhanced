#!/usr/bin/env python3
"""assemble_lock — the per-dir re-render lock for assemble.py.

Concurrent assembles on ONE output dir are destructive (audit-confirmed: both
runs write final.mp4, and --auto-base promotes the staged refit over the
operator's plan), so assemble.main() is serialized by a lockfile:

    <out dir>/.assemble.lock   containing {"pid": N, "startedAt": ISO-8601}

Protocol:
  * lock held by a LIVE pid → the new run emits
    ``{"error": "another re-render is already running for this dir (pid N)"}``
    and exits 1 — it must NEVER remove the holder's lock.
  * lock whose pid is dead (or an unreadable lock — a crashed run's partial
    write) is STALE: replaced with a loud ``stale_lock_replaced`` warning so a
    crash never wedges the editor.
  * the acquiring run removes the lock in its ``finally`` — on success AND on
    failure.
  * the check-then-write inside ``acquire_lock`` is serialized by a kernel
    flock on ``<lock>.mutex`` (see ``_meta_mutex``), so two racing acquirers
    can never both read "no live holder" and both write the lock. The mutex
    is kernel-owned — released on process death, so it cannot wedge — and its
    file is never unlinked (unlink+recreate would hand two racers flocks on
    different inodes).
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the render stages)."""
    print(json.dumps(fields), flush=True)


def pid_alive(pid: int) -> bool:
    """True if a process with ``pid`` exists (signal-0 probe, no signal sent)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # exists, owned by another user
    return True


def _meta_mutex(lock_path: str) -> int:
    """fd holding an EXCLUSIVE kernel flock on ``<lock>.mutex``.

    Serializes ``acquire_lock``'s check-then-write (a µs critical section, so
    blocking is fine). Kernel-owned: a holder that dies releases it, so it can
    never wedge. The mutex file itself is never unlinked.
    """
    fd = os.open(lock_path + ".mutex", os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def acquire_lock(lock_path: str) -> bool:
    """Take the per-dir re-render lock; False = a LIVE run already holds it.

    The caller owns removal (its ``finally``) ONLY when this returns True —
    a blocked run must never delete the live holder's lock.
    """
    meta = _meta_mutex(lock_path)
    try:
        if os.path.exists(lock_path):
            try:
                with open(lock_path) as f:
                    holder = json.load(f)
            except (OSError, json.JSONDecodeError):
                holder = {}   # unreadable lock → no live pid to respect → stale
            pid = holder.get("pid")
            if isinstance(pid, int) and pid_alive(pid):
                emit(error="another re-render is already running for this dir "
                           f"(pid {pid})")
                return False
            emit(status="stale_lock_replaced", path=lock_path,
                 warning=f"stale .assemble.lock (pid {pid} is not running) — "
                         "replacing it")
        with open(lock_path, "w") as f:
            json.dump({"pid": os.getpid(),
                       "startedAt": datetime.now(timezone.utc)
                       .isoformat(timespec="seconds")}, f)
        return True
    finally:
        fcntl.flock(meta, fcntl.LOCK_UN)
        os.close(meta)
