"""Transport-neutral progress events for visible Palmier native mutations."""
from __future__ import annotations

from collections.abc import Callable

Progress = Callable[[dict], None]


class NativeProgress:
    """Report only mutation boundaries that have a verified Palmier readback."""

    def __init__(self, callback: Progress | None = None):
        self._callback = callback

    def _send(self, status: str, **fields: object) -> None:
        if self._callback is not None:
            self._callback({"event": "palmier_native_progress",
                            "status": status, **fields})

    def candidate_active(self, candidate: dict) -> None:
        self._send("candidate_active", timelineId=candidate["timelineId"],
                   message="Palmier candidate is active; governed edits are landing now.")

    def operation_applied(self, receipt: dict, total: int) -> None:
        self._send("operation_applied", index=receipt["index"], total=total,
                   tool=receipt["tool"], reason=receipt["reason"],
                   afterFingerprint=receipt["afterFingerprint"])

    def parent_restored(self, authority: dict, candidate: dict) -> None:
        self._send("parent_restored", timelineId=authority["timelineId"],
                   candidateTimelineId=candidate["timelineId"],
                   message="Governed candidate is saved; the verified parent is visible during QC.")

    def candidate_visible(self, candidate: dict) -> None:
        self._send("candidate_visible", timelineId=candidate["timelineId"],
                   message="The editable candidate remains visible while exact-timeline QC runs.")
