"""The export watchdog's process work: stop its child, then end the child's group and own-session children.

The exporter child leads its own process group (the watchdog starts it in a new session). Its
native owners (``native_run.NativeRun``) and bounded helpers (``headless.process_runner``) start
children in sessions of their own, outside that group; both record each one in the ledger the
watchdog names (``headless.process_runner.LEDGER_ENV`` → ``owned-sessions.jsonl`` in the claim
directory). ``end_group`` runs once the child has exited but before it is reaped, so its group id
stays reserved: it SIGKILLs the child's group and every recorded session that is still alive by
exact identity (a group leader whose start is no later than its ledger row and no earlier than the
watchdog's start), reaps the child, and waits up to ``REAP_SECONDS`` for all of them to be gone.
What survives is returned and keeps the task's slot. Known limits: processes a render worker started
in further sessions of their own are not in this ledger (the pool's recorded lease identities and
quarantine cover them, ``native_work_recovery.py``), and a helper whose runner was killed between its
``intent`` and ``spawned`` rows is not identified (it is not a heavy job: those hold pool leases).
"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from native_render_processes import ResourceMeasurementError
from studio import native_budget_launch as launch
from studio.production import process

LSTART = '%a %b %d %H:%M:%S %Y'   # ps lstart under native_budget_launch.PS_ENVIRONMENT (C locale, UTC)


def exited(pid: int) -> bool:
    """Whether this unreaped child has exited, without reaping it (its pid and group stay reserved)."""
    try:
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError:
        return True


def terminate(child: subprocess.Popen, wait: Callable[[float], None]) -> None:
    """SIGTERM the child and allow its owned cleanup for the grace; the child is not reaped here.

    ``wait(seconds)`` passes the time (the watchdog keeps relaying the child's output meanwhile).
    """
    deadline = time.monotonic() + process.STOP_GRACE_SECONDS
    with suppress(ProcessLookupError):
        os.kill(child.pid, signal.SIGTERM)
    while not exited(child.pid) and time.monotonic() < deadline:
        wait(0.05)


def _table() -> dict | None:
    """One process-table read (pid → (ppid, pgid, lstart)); None when unreadable."""
    try:
        return launch._process_table()
    except (OSError, subprocess.SubprocessError, ResourceMeasurementError):
        return None


def _started(text: str) -> float | None:
    """The epoch second of a ps lstart value, or None."""
    try:
        return datetime.strptime(text, LSTART).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _rows(file: Path) -> list[dict]:
    """Read complete evidence; a killed writer's partial row leaves cleanup uncertain."""
    if file.stat().st_size > 16 * 1024 ** 2:
        raise ValueError('Owned session ledger exceeds its inspection bound')
    rows = []
    for line in file.read_text(errors='replace').splitlines():
        row = json.loads(line)
        if type(row) is not dict:
            raise ValueError('Owned session ledger contains a non-object row')
        rows.append(row)
    return rows


def _spawned(rows: list[dict]) -> dict[int, float]:
    """Malformed launch evidence or an unmatched pre-spawn intent cannot prove cleanup."""
    intents = sum(row.get('event') == 'intent' for row in rows)
    failed = sum(row.get('event') == 'spawn-failed' for row in rows)
    launches = [row for row in rows if row.get('event') == 'spawned']
    if intents > len(launches) + failed:
        raise ValueError('Owned session launch intent has no confirmed spawn outcome')
    if any(type(row.get('pid')) is not int or row['pid'] <= 1
           or type(row.get('at')) not in (int, float) or not math.isfinite(row['at']) for row in launches):
        raise ValueError('Owned session ledger has malformed spawned identity')
    return {row['pid']: row['at'] for row in launches}


def _members(table: dict, group: int) -> list[dict]:
    """All members of one group at this observation, with exact identities."""
    return [{'type': 'process', 'pid': pid, 'pgid': row[1], 'started': row[2]}
            for pid, row in table.items() if row[1] == group]


def _unknown(group: int) -> dict:
    """An unresolved marker, never authority to signal or automatically clear a group."""
    return {'type': 'process', 'pid': group, 'pgid': group, 'started': 'unobservable'}


def ledger_sessions(directory: Path, since: float, table: dict | None) -> list[dict]:
    """Bind entire recorded sessions while their leader identity is still provable."""
    file = directory / process.LEDGER
    if table is None or not file.is_file():
        return []
    spawned = _spawned(_rows(file))
    sessions = []
    for pid, at in spawned.items():
        started = _started(table[pid][2]) if pid in table and table[pid][1] == pid else None
        members = _members(table, pid)
        if started is not None and since - 1 <= started <= at + 1:
            sessions.extend(members)
        elif members:
            sessions.append(_unknown(pid))  # leader already exited/reused: no safe group signal
    return sessions


def _matches(table: dict, row: dict) -> bool:
    """An exact previously observed member still anchors its original process group."""
    return row['started'] != 'unobservable' and table.get(row['pid'], (None, None, None))[1:] \
        == (row['pgid'], row['started'])


def _session_survivors(table: dict, sessions: list[dict]) -> list[dict]:
    """Leader death does not erase descendants; lost group identity remains unresolved."""
    survivors = []
    for group in sorted({row['pgid'] for row in sessions}):
        known = [row for row in sessions if row['pgid'] == group]
        members = _members(table, group)
        if any(row['started'] == 'unobservable' for row in known):
            survivors.append(_unknown(group))
        elif members:
            survivors.extend(members if any(_matches(table, row) for row in known) else [_unknown(group)])
    return survivors


def _living(child_group: int, sessions: list[dict]) -> list[dict]:
    """Track full detached groups, including descendants whose leader has exited."""
    table = _table()
    if table is None:
        return [_unknown(child_group)]
    live_sessions = _session_survivors(table, sessions)
    sessions[:] = live_sessions  # carry newly observed anchored descendants and unresolved markers
    return _members(table, child_group) + live_sessions


def _kill_sessions(sessions: list[dict]) -> None:
    """Recheck a live identity before signaling each detached group; never signal unknown markers."""
    for group in sorted({row['pgid'] for row in sessions}):
        known = [row for row in sessions if row['pgid'] == group]
        if any(row['started'] == 'unobservable' for row in known):
            continue
        table = _table()
        if table is None:
            sessions.append(_unknown(group))
            continue
        if any(_matches(table, row) for row in known):
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(group, signal.SIGKILL)


def end_group(child: subprocess.Popen, directory: Path, since: float) -> list[dict]:
    """End the exited (or stopped) child's group and recorded sessions; return the identities that survive."""
    table = _table()
    try:
        sessions = ledger_sessions(directory, since, table)
    except (OSError, ValueError, TypeError):
        table, sessions = None, []  # retain unresolved cleanup, but still stop the exporter group
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)  # unreaped child reserves its own group identity
    _kill_sessions(sessions)
    with suppress(subprocess.TimeoutExpired):
        child.wait(timeout=process.REAP_SECONDS)
    deadline = time.monotonic() + process.REAP_SECONDS
    survivors = _living(child.pid, sessions)
    while survivors and time.monotonic() < deadline:
        time.sleep(0.1)
        survivors = _living(child.pid, sessions)
    if table is None or len(survivors) > 16:
        # A later readable table cannot reconstruct the detached sessions omitted above.
        return [_unknown(child.pid), *(row for row in survivors if row['pid'] != child.pid)][:16]
    return survivors[:16]
