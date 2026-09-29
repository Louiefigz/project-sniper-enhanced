"""A host process launched by a probe, with its exact handle and a timestamped event reader.

The child starts in its own session so the probe can name its process group, and
stdout JSON lines are recorded with monotonic receive times. The reader never
interprets events; scenarios decide what an event means.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from studio.production.host_conformance import procs


@dataclass(frozen=True)
class Launch:
    """Exact argv, working directory, environment and raw log for one host child."""

    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    raw_log: Path


class EventLog:
    """Timestamped JSON events from one transport, waitable by predicate."""

    def __init__(self) -> None:
        """Start the clock every stamp is measured on."""
        self.t0 = time.monotonic()
        self.events: list[tuple[float, dict]] = []
        self.cond = threading.Condition()

    def reading(self) -> bool:
        """Whether more events can still arrive; transports override."""
        return False

    def record(self, line: str) -> None:
        """Stamp one line on the launch clock and wake waiters; non-JSON is kept raw."""
        try:
            event = json.loads(line)
        except ValueError:
            event = {"_raw": line.rstrip("\n")[:500]}
        if not isinstance(event, dict):
            event = {"_raw": line.rstrip("\n")[:500]}
        with self.cond:
            self.events.append((round(time.monotonic() - self.t0, 3), event))
            self.cond.notify_all()

    def elapsed(self) -> float:
        """Seconds since start on the same clock as event stamps."""
        return round(time.monotonic() - self.t0, 3)

    def _poll(self, predicate: Callable[[dict], bool],
              remaining: float) -> tuple[float, dict] | None:
        """One bounded wait step: the first match so far, else wait for more events."""
        with self.cond:
            found = next(((s, e) for s, e in self.events if predicate(e)), None)
            if found is None and remaining > 0 and self.reading():
                self.cond.wait(min(remaining, 0.5))
            return found

    def wait_event(self, predicate: Callable[[dict], bool],
                   timeout_s: float) -> tuple[float, dict] | None:
        """First event (any time) matching predicate, waiting up to timeout."""
        deadline = time.monotonic() + timeout_s
        found = self._poll(predicate, timeout_s)
        while found is None and time.monotonic() < deadline and self.reading():
            found = self._poll(predicate, deadline - time.monotonic())
        return found or self._poll(predicate, 0)

    def snapshot(self) -> list[tuple[float, dict]]:
        """Copy of all events so far."""
        with self.cond:
            return list(self.events)


class StreamChild(EventLog):
    """One launched host process and the JSON events it has emitted on stdout."""

    def __init__(self, launch: Launch) -> None:
        """Spawn the child in a new session and start reading stdout."""
        super().__init__()
        self.launch = launch
        launch.raw_log.parent.mkdir(parents=True, exist_ok=True)
        self._stderr = open(launch.raw_log.with_suffix(".stderr"), "w")
        self.proc = subprocess.Popen(
            list(launch.argv), cwd=launch.cwd, env=launch.env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self._stderr, text=True, bufsize=1,
            start_new_session=True)
        self.identity = procs.identity_of(self.proc.pid)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def reading(self) -> bool:
        """True while stdout is still being read."""
        return self._reader.is_alive()

    def _read(self) -> None:
        """Record every stdout line and keep the raw log."""
        with open(self.launch.raw_log, "w") as log:
            for line in self.proc.stdout:
                log.write(line)
                log.flush()
                self.record(line)

    def send(self, message: dict) -> float:
        """Write one JSON line to stdin; returns the send time."""
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        return self.elapsed()

    def close_stdin(self) -> None:
        """Signal end of input the way a disconnecting coordinator would."""
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()

    def wait_exit(self, timeout_s: float) -> int | None:
        """Exit code, or None if the child outlived the window."""
        try:
            return self.proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return None

    def stderr_tail(self, limit: int = 800) -> str:
        """Last bytes of the child's stderr, for refusal evidence."""
        self._stderr.flush()
        text = self.launch.raw_log.with_suffix(".stderr").read_text(errors="replace")
        return text[-limit:]
