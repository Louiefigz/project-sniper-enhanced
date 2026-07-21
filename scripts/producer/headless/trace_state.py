"""Closed reboot, recovery, and terminal rules for attempt trace frames."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BOOT_TRANSITION_EVENTS = frozenset({"RECOVERY_RESUMED", "TERMINAL_SEALED"})
TAIL_REPAIR_EVENTS = BOOT_TRANSITION_EVENTS | {"ADMITTED"}
RECOVERY_REASONS = frozenset({"HOST_REBOOT", "PROCESS_CRASH", "TORN_TAIL"})
TERMINAL_DISPOSITIONS = frozenset(
    {"BLOCKED", "CANCELED", "FAILED", "STALE", "SUCCEEDED"})
_DIGEST_LENGTH = 64
_PHASE_TRANSITIONS = {
    "ADMITTED": ({None}, "ADMITTED"),
    "WORKER_START": ({"ADMITTED", "RUNNING"}, "RUNNING"),
    "VERIFIED": ({"RUNNING"}, "VERIFIED"),
    "PUBLISH_INTENT": ({"VERIFIED"}, "PUBLISH_INTENT"),
    "POINTER_COMMITTED": ({"PUBLISH_INTENT"}, "POINTER_COMMITTED"),
}


class TraceStateViolation(RuntimeError):
    """An otherwise valid frame violates the trace lifecycle."""


@dataclass(frozen=True)
class ClockState:
    """Boot-scoped monotonic state accumulated while scanning the chain."""

    boot_id: str | None = None
    monotonic_ns: int = 0
    seen_boot_ids: frozenset[str] = frozenset()
    terminal: bool = False
    phase: str | None = None


def validate_event_contract(payload: dict[str, Any]) -> None:
    """Validate the closed schemas used for recovery and terminal authority."""
    event = payload["event"]
    details = payload["details"]
    recovery = payload.get("traceRecovery")
    if recovery is not None and event not in TAIL_REPAIR_EVENTS:
        raise TraceStateViolation("torn-tail repair requires recovery or terminal")
    if event == "RECOVERY_RESUMED":
        if set(details) != {"reasonCode"} or details["reasonCode"] not in RECOVERY_REASONS:
            raise TraceStateViolation("RECOVERY_RESUMED has an invalid reasonCode")
    if event == "TERMINAL_SEALED":
        result_digest = details.get("resultDigest")
        valid = (set(details) == {"disposition", "resultDigest"}
                 and details["disposition"] in TERMINAL_DISPOSITIONS
                 and isinstance(result_digest, str)
                 and len(result_digest) == _DIGEST_LENGTH
                 and all(char in "0123456789abcdef" for char in result_digest))
        if not valid:
            raise TraceStateViolation("TERMINAL_SEALED has an invalid disposition")


def _advance_phase(phase: str | None, payload: dict[str, Any]) -> str:
    event = payload["event"]
    if event == "TERMINAL_SEALED":
        if phase is None:
            raise TraceStateViolation("terminal seal requires durable admission")
        if payload["details"]["disposition"] == "SUCCEEDED" \
                and phase != "POINTER_COMMITTED":
            raise TraceStateViolation("success requires a committed pointer")
        return phase
    if event == "RECOVERY_RESUMED":
        if phase is None:
            raise TraceStateViolation("recovery requires durable admission")
        return phase
    if phase is None and event != "ADMITTED":
        raise TraceStateViolation("the first trace event must be ADMITTED")
    transition = _PHASE_TRANSITIONS.get(event)
    if transition is not None:
        allowed, next_phase = transition
        if phase not in allowed:
            raise TraceStateViolation(f"{event} is invalid after {phase or 'EMPTY'}")
        return next_phase
    return phase


def _validate_clock_transition(state: ClockState, payload: dict[str, Any]) -> None:
    boot_id = payload["bootId"]
    same_boot = state.boot_id == boot_id
    if same_boot and payload["monotonicNs"] < state.monotonic_ns:
        raise TraceStateViolation("monotonic clock moved backward within one boot")
    if same_boot or state.boot_id is None:
        return
    if boot_id in state.seen_boot_ids:
        raise TraceStateViolation("a prior boot identity cannot recur")
    if payload["event"] not in BOOT_TRANSITION_EVENTS:
        allowed = "|".join(sorted(BOOT_TRANSITION_EVENTS))
        raise TraceStateViolation(f"boot transition requires {allowed}")


def advance_clock(state: ClockState, payload: dict[str, Any]) -> ClockState:
    """Advance one frame, rejecting reboot bounce and post-terminal work."""
    if state.terminal:
        raise TraceStateViolation("terminal trace state is absorbing")
    boot_id = payload["bootId"]
    _validate_clock_transition(state, payload)
    return ClockState(
        boot_id=boot_id,
        monotonic_ns=payload["monotonicNs"],
        seen_boot_ids=state.seen_boot_ids | {boot_id},
        terminal=payload["event"] == "TERMINAL_SEALED",
        phase=_advance_phase(state.phase, payload),
    )
