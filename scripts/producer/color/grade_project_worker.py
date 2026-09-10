"""Owned-pipe entry for the internal project observation service, not a CLI UI.

The deadline handshake never compares Node/Python clock origins: the controller
adds only its still-remaining budget to a Python sample that preceded receipt.
That conservatively shortens the child budget by the IPC transit time.
"""
from __future__ import annotations

import json
import re
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from color.deadline import wall_budget
from color.grade_project import run_project_observation
from color.grade_observation_profile import V2_PROFILE, observation_profile
from color.grade_project_input import (read_grade_project_input as _input,
                                       verify_grade_project_implementation as _held_implementation)
from cut_preview_io import file_hash


def _handshake(profile: str | None = None) -> float:
    """Accept at most one conservative deadline over this owned stdin pipe."""
    maximum = observation_profile(profile).max_seconds
    sample = time.monotonic_ns()
    print(json.dumps({"readyMonotonicNs": str(sample)}), flush=True)
    # Bound a disappeared/unresponsive server before any container is launched.
    with wall_budget(time.monotonic() + 5):
        line = sys.stdin.readline(4097)
    if len(line) > 4096 or not line.endswith("\n"):
        raise RuntimeError("project observation owner handshake is unavailable")
    row = json.loads(line)
    if type(row) is not dict or set(row) != {"deadlineMonotonicNs"} \
            or type(row["deadlineMonotonicNs"]) is not str or not re.fullmatch(r"[0-9]{1,24}", row["deadlineMonotonicNs"]):
        raise RuntimeError("project observation deadline handshake is malformed")
    deadline = int(row["deadlineMonotonicNs"])
    if not time.monotonic_ns() < deadline <= sample + maximum * 1_000_000_000:
        raise RuntimeError("project observation remaining budget is invalid or exhausted")
    return deadline / 1_000_000_000


def _owner_expired(_signal: int, _frame: object) -> None:
    """Cancel owned work; the policy masks this signal during daemon cleanup."""
    raise RuntimeError("project observation owner work deadline exceeded; cleanup is separate")


def main() -> None:
    """Independently accept owner cancellation without severing daemon cleanup."""
    if len(sys.argv) not in (3, 5) or (len(sys.argv) == 5 and sys.argv[3:] != ["--profile", V2_PROFILE]):
        raise SystemExit("internal project observation owner invocation required")
    profile = V2_PROFILE if len(sys.argv) == 5 else None
    # Both the child ALRM and the parent's original deadline can cancel work.
    # Neither grants a fresh work budget or permits late success publication.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGUSR1, _owner_expired)
    deadline = _handshake(profile)
    path = Path(sys.argv[1])
    with wall_budget(deadline):
        value = _input(path, sys.argv[2], profile)
        _held_implementation(path.parent, value)
    result = run_project_observation(value, path.parent, deadline)
    with wall_budget(deadline if result["status"] == "complete" else time.monotonic() + 5):
        _held_implementation(path.parent, value)
        print(json.dumps({"resultSha256": file_hash(path.parent / "observation.json"),
            "cleanupVerified": result["cleanupVerified"], "status": result["status"]}), flush=True)


if __name__ == "__main__":
    main()
