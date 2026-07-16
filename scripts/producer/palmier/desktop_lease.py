"""Lease renewal for an unchanged Desktop Palmier candidate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from palmier.desktop_state import append_journal, load_pointer, now, save_state
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import read_active


def renew(client: Any, repo: str, hours: float = 3.0) -> dict:
    """Extend a candidate lease without changing its stage or approval state."""
    if hours <= 0 or hours > 12:
        raise PalmierError("Desktop Palmier lease must be within 0-12 hours")
    _path, state = load_pointer(repo)
    found = read_active(client, state["projectId"])
    current = state.get("candidate") or {}
    if found.timeline_id != current.get("timelineId") \
            or found.fingerprint != state.get("expectedFingerprint"):
        raise PalmierError("Palmier candidate drifted before lease renewal")
    if state.get("pendingOperation"):
        raise PalmierError("reconcile the pending Palmier operation before renewal")
    current_time = datetime.now(timezone.utc)
    ceiling = current_time + timedelta(hours=12)
    try:
        prior = datetime.fromisoformat(str(state.get("expiresAt")))
    except ValueError:
        prior = current_time
    if prior.tzinfo is None:
        prior = prior.replace(tzinfo=timezone.utc)
    expires = min(max(current_time, prior) + timedelta(hours=hours), ceiling)
    state.update({"expiresAt": expires.isoformat(timespec="seconds"),
                  "updatedAt": now()})
    append_journal(state, {"event": "desktop_lease_renewed", "at": now(),
                           "expiresAt": state["expiresAt"]})
    return save_state(repo, state)
