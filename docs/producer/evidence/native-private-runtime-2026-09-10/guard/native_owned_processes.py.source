"""Track only this invocation's descendants, including detached browser groups."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class OwnedProcess:
    """A PID bound to its observed start, with group and parent evidence."""

    pid: int
    parent_pid: int
    pgid: int
    started: str


def read_processes() -> dict[int, OwnedProcess]:
    """Fail explicitly when the host process table cannot be read."""
    result = subprocess.run(
        ['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='],
        text=True, capture_output=True, check=True, timeout=3,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    rows = [re.fullmatch(r'\s*(\d+)\s+(\d+)\s+(\d+)\s+(.+?)\s*', line) for line in lines]
    if not rows or any(row is None for row in rows):
        raise RuntimeError('Host process table is empty or malformed')
    if len({row[1] for row in rows}) != len(rows):
        raise RuntimeError('Host process table contains duplicate PIDs')
    return {int(pid): OwnedProcess(int(pid), int(parent), int(group), started.strip())
            for pid, parent, group, started in (row.groups() for row in rows)}


class OwnedRegistry:
    """Retain ownership after reparenting; never select processes by name."""

    def __init__(self, root_pid: int) -> None:
        """Bind the newly spawned leader before accepting any group authority."""
        table = read_processes()
        root = table.get(root_pid)
        if root is None or root.pgid != root_pid or root.parent_pid != os.getpid():
            raise RuntimeError('New child process-group ownership could not be bound')
        self.root_pid = root_pid
        self.known = {root_pid: root}
        self.groups = {root_pid}
        self.signal_events: list[dict] = []
        self.live(table)

    def live(self, table: dict[int, OwnedProcess] | None = None) -> dict[int, OwnedProcess]:
        """Discover descendants and retain only matching, currently live identities."""
        table = read_processes() if table is None else table
        live = {pid: row for pid, row in table.items()
                if pid in self.known and row.started == self.known[pid].started}
        while True:
            anchored = {row.pgid for row in live.values() if row.pgid in self.groups}
            added = {pid: row for pid, row in table.items() if pid not in live
                     and (row.parent_pid in live or row.pgid in anchored)}
            if not added:
                break
            live.update(added)
        self.known.update(live)
        self.groups.update(row.pgid for row in live.values() if row.pid == row.pgid)
        return live

    def identities(self) -> list[dict]:
        """Export currently verified identities for the independent memory sampler."""
        return [asdict(row) for row in self.live().values()]

    def remember_measured(self, processes: tuple) -> None:
        """Retain internally verified sampler discoveries through reparenting."""
        for measured in processes:
            row = OwnedProcess(measured.pid, measured.parent_pid, measured.pgid, measured.started)
            prior = self.known.get(row.pid)
            if prior and (prior.started, prior.pgid) != (row.started, row.pgid):
                raise RuntimeError('Measured PID conflicts with recorded cleanup identity')
            self.known[row.pid] = row
            if row.pid == row.pgid:
                self.groups.add(row.pgid)

    def signal_owned(self, value: signal.Signals) -> None:
        """Recheck identity before signalling each owned group or individual."""
        live = self.live()
        groups = sorted({row.pgid for row in live.values() if row.pgid in self.groups},
                        key=lambda group: group == self.root_pid)
        for group in groups:
            current = self.live()
            anchors = [row for row in current.values() if row.pgid == group]
            if anchors:
                self._send(-group, value, anchors)
        remaining = self.live()
        for row in remaining.values():
            if row.pgid not in groups:
                self._send(row.pid, value, [row])

    def _send(self, target: int, value: signal.Signals, anchors: list[OwnedProcess]) -> None:
        """Record exact authority and preserve permission errors as cleanup failures."""
        evidence = {'at': time.time(), 'target': target, 'signal': value.name,
                    'anchors': [asdict(row) for row in anchors]}
        try:
            os.kill(target, value)
            evidence['outcome'] = 'sent'
        except ProcessLookupError:
            evidence['outcome'] = 'already-exited'
        except PermissionError:
            remaining = self.live()
            still_owned = any(row.pgid == -target if target < 0 else row.pid == target
                              for row in remaining.values())
            evidence['outcome'] = 'permission-denied' if still_owned else 'exited-during-signal'
            if still_owned:
                self.signal_events.append(evidence)
                raise
        self.signal_events.append(evidence)

    def cleanup(self, child: subprocess.Popen) -> dict:
        """Bound cancellation, reap the direct child, then verify surviving identities."""
        for value, grace in [(signal.SIGINT, 1), (signal.SIGTERM, 2), (signal.SIGKILL, 2)]:
            self.signal_owned(value)
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                child.poll()
                if not self.live():
                    child.wait(timeout=1)
                    return {'verified': True, 'survivors': [], 'signals': self.signal_events,
                            'scope': 'Recorded owned identities; not an unobserved-child guarantee'}
                time.sleep(.1)
        survivors = [asdict(row) for row in self.live().values()]
        return {'verified': not survivors and child.poll() is not None,
                'survivors': survivors, 'signals': self.signal_events,
                'scope': 'Recorded owned identities; not an unobserved-child guarantee'}
