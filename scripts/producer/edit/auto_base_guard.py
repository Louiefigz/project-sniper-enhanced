#!/usr/bin/env python3
"""auto_base_guard — quarantine a stale base before assembling a FRESH plan.

``assemble.py --auto-base`` refits a stale plan's OUTPUT-time windows from the
OLD base timebase (``edit/plan_refit.py``). That is correct for the EDITOR
flow — the operator edited the cutTrack underneath windows that were authored
against the current base. The AUTO-EDIT lane is the opposite case: the brain
just authored EVERY window against its OWN cutTrack (already the new
timebase), so running the refit would remap correct windows through the old
map and corrupt them.

This guard makes the rebuild refit-free: unless the freshly authored plan's
VIDEO fingerprint PROVABLY matches the recorded base, ``base_final.mp4`` is
renamed to ``base_final.prev.mp4`` so ``ensure_base`` sees state ``missing``
(full rebuild from the plan AS WRITTEN — the refit only stages on ``stale``).
That includes a fingerprint-less base: the editor tolerates ``unverifiable``
(don't block a human), but an auto-authored plan almost never matches an
unproven base — assembling onto it would silently ship the OLD timeline.
A matching video fingerprint keeps the base untouched, so the fast paths
(graphics-only composite, audio-only bus rebuild) stay available.

It refuses to touch a dir whose ``.assemble.lock`` is held by a LIVE pid —
renaming the base under a running re-render is destructive.

CLI: auto_base_guard.py <dir>    # dir holding edit_plan.json / base_final.mp4
Output: one NDJSON line {"event": "auto_base_guard", "action": ...}; exit 1
with {"status": "error", ...} on a live lock / unreadable plan (fail loudly).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # producer pkg root

from assemble_lock import pid_alive
from fingerprints import recorded_fingerprints, video_fingerprint


def _live_lock_pid(lock_path: str) -> int | None:
    """The pid holding the lock if it is alive, else None (absent/stale)."""
    if not os.path.exists(lock_path):
        return None
    try:
        with open(lock_path) as f:
            pid = json.load(f).get("pid")
    except (OSError, json.JSONDecodeError):
        return None   # unreadable lock = crashed writer = stale
    if isinstance(pid, int) and pid_alive(pid):
        return pid
    return None


def guard(out_dir: str) -> dict:
    """Quarantine a stale base; return the NDJSON-able action record.

    Raises ``RuntimeError`` on a live .assemble.lock and ``OSError``/
    ``json.JSONDecodeError`` on an unreadable plan — the caller reports.
    """
    pid = _live_lock_pid(os.path.join(out_dir, ".assemble.lock"))
    if pid is not None:
        raise RuntimeError(f"another re-render is already running for this "
                           f"dir (pid {pid}) — not touching its base")
    base = os.path.join(out_dir, "base_final.mp4")
    fingerprint = os.path.join(out_dir, "base.fingerprint.json")
    with open(os.path.join(out_dir, "edit_plan.json")) as f:
        plan = json.load(f)
    if not os.path.exists(base):
        return {"action": "none", "reason": "no base — assemble rebuilds from scratch"}
    reason = "fresh plan vs unproven base — forcing a no-refit full rebuild"
    if os.path.exists(fingerprint):
        recorded = recorded_fingerprints(fingerprint).get("videoFingerprint")
        if recorded and recorded == video_fingerprint(plan):
            return {"action": "none",
                    "reason": "video fingerprint matches — fast paths stay valid"}
        reason = "fresh plan vs stale base — forcing a no-refit full rebuild"
    prev = os.path.join(out_dir, "base_final.prev.mp4")
    os.replace(base, prev)
    return {"action": "quarantined", "moved": prev, "reason": reason}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"status": "error",
                          "error": "usage: auto_base_guard.py <dir>"}), flush=True)
        return 1
    try:
        record = guard(sys.argv[1].rstrip("/"))
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), flush=True)
        return 1
    print(json.dumps({"event": "auto_base_guard", **record}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
