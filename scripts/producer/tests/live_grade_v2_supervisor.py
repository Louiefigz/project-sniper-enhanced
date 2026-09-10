"""TEST-only pre-claim blocked session; fixed worker fork only after exact permit.

The outer owner independently observes group absence. This supervisor never
claims that its own exit proves absence of descendants or Docker resources.
"""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cut_preview_io import bound_json, file_hash, real_directory


def _permit_object(raw: bytes) -> dict:
    """Reject nonobject activation without a nested wait-loop branch."""
    value = json.loads(raw)
    if type(value) is not dict:
        raise RuntimeError("Fork permit must be an object")
    return value


def read_permit(parent: int, deadline: float) -> dict:
    """Read one bounded line without prefetching the subsequent worker handshake."""
    raw = bytearray()
    while time.monotonic() < deadline and os.getppid() == parent:
        if not select.select([0], [], [], min(.1, max(0, deadline - time.monotonic())))[0]:
            continue
        part = os.read(0, 1)
        if not part:
            raise RuntimeError("Owner pipe closed before fork permit")
        raw.extend(part)
        if part == b"\n":
            return _permit_object(raw)
        if len(raw) > 4096:
            raise RuntimeError("Fork permit exceeds bound")
    raise RuntimeError("Owner absent or original fork deadline expired")


def validate_permit(row: dict, parent: int) -> tuple[list[str], float]:
    """Cross-bind immutable lifecycle, exact active claim and input before fork."""
    if set(row) != {"directory", "lifecycleSha256", "claimPath", "claimSha256"}:
        raise RuntimeError("Malformed exact fork permit")
    directory = Path(row["directory"])
    real_directory(directory)
    life = bound_json(directory / "TEST-lifecycle.json", row["lifecycleSha256"])
    claim = bound_json(Path(row["claimPath"]), row["claimSha256"])
    expected = {"jobId": directory.name, "dir": life["producerDir"],
                "requestDigest": life["inputSha256"], "lifecycleSha256": row["lifecycleSha256"]}
    if claim != expected or sys.executable != life["python"] \
            or row["claimPath"] != str(Path(life["resource"]) / "active.json") \
            or life["directory"] != str(directory) \
            or life["supervisor"]["pid"] != os.getpid() or life["owner"]["pid"] != parent:
        raise RuntimeError("Fork permit differs from original owner claim")
    for pin in life["pins"]:
        if file_hash(Path(pin["path"]), 128 * 1024 * 1024) != pin["sha256"]:
            raise RuntimeError("Held supervisor/worker code changed before fork")
    value = bound_json(directory / "input.json", life["inputSha256"])
    if value["ownerPid"] != os.getpid() or value["jobId"] != directory.name:
        raise RuntimeError("Worker input does not name this supervisor")
    script = Path(__file__).with_name("live_grade_v2_launch.py")
    command = [sys.executable, "-I", "-S", "-B", str(script), str(directory), row["lifecycleSha256"]]
    return command, int(life["supervisorDeadlineNs"]) / 1e9


def supervise(command: list[str], parent: int, deadline: float, cleanup_seconds: float = 100) -> int:
    """Keep leaf children in this group; cancel on owner death without new work credit."""
    if os.getppid() != parent or time.monotonic() >= deadline or not 0 < cleanup_seconds <= 100:
        raise RuntimeError("Original owner or fork deadline unavailable")
    child = subprocess.Popen(command, start_new_session=False)
    cancelled = False
    def cancel(_sig: int, _frame: object) -> None:
        """Forward work cancellation only to the actual unreaped child."""
        nonlocal cancelled
        if child.poll() is None:
            child.send_signal(signal.SIGUSR1)
        cancelled = True
    signal.signal(signal.SIGUSR1, cancel)
    signal.signal(signal.SIGTERM, cancel)
    while child.poll() is None:
        if not cancelled and (os.getppid() != parent or time.monotonic() >= deadline):
            cancel(signal.SIGUSR1, None)
        if time.monotonic() >= deadline + cleanup_seconds:
            child.kill()
            return child.wait(timeout=2)
        time.sleep(.02)
    return child.returncode


def main() -> None:
    """Only a POSIX session leader with a live pipe owner may await activation."""
    if len(sys.argv) != 3 or not sys.argv[1].isdigit() or not sys.argv[2].isdigit():
        raise RuntimeError("Internal TEST supervisor requires parent and bounded wait")
    parent, wait_ms = int(sys.argv[1]), int(sys.argv[2])
    if parent != os.getppid() or os.getpid() != os.getpgrp() or os.getpid() != os.getsid(0) \
            or not 1 <= wait_ms <= 120000:
        raise RuntimeError("Invalid owned supervisor group or deadline")
    sample = time.monotonic_ns()
    deadline = sample / 1e9 + wait_ms / 1000
    print(json.dumps({"supervisorReady": os.getpid(), "readyMonotonicNs": str(sample)}), flush=True)
    permit = read_permit(parent, deadline)
    command, held_deadline = validate_permit(permit, parent)
    if not time.monotonic() < held_deadline <= deadline:
        raise RuntimeError("Original translated supervisor deadline unavailable")
    raise SystemExit(supervise(command, parent, held_deadline))


if __name__ == "__main__":
    main()
