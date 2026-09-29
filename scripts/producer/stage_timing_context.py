"""Process-local timing lineage shared with the TypeScript controller.

Lineage is telemetry identity only: run/attempt/parent span plus optional task, claim
epoch and host turn. It never authorizes, admits, claims or settles work; the
authoritative task and claim transitions live in the production authority.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import uuid
from typing import Iterator

PARENT_SPAN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sniper_timing_parent_span", default=None)
_TASK: contextvars.ContextVar[tuple[dict, list[str]] | None] = contextvars.ContextVar(
    "sniper_timing_task", default=None)
_WRITER_ID = str(uuid.uuid4())
_TEXT_KEYS = ("provider", "model", "effort", "phase", "cache")
_NUMBER_KEYS = ("round", "packetBytes", "evidenceImages", "exitCode")
MAX_ID_LENGTH = 256
MAX_EPOCH = 2**53 - 1
# The only environment a closed child receives for timing: field -> variable.
LINEAGE_ENV = {
    "runId": "SNIPER_TIMING_RUN_ID", "attemptId": "SNIPER_TIMING_ATTEMPT_ID",
    "attemptNo": "SNIPER_TIMING_ATTEMPT_NO", "parentSpanId": "SNIPER_TIMING_PARENT_SPAN_ID",
    "taskId": "SNIPER_TIMING_TASK_ID", "claimEpoch": "SNIPER_TIMING_CLAIM_EPOCH",
    "hostTurnId": "SNIPER_TIMING_HOST_TURN_ID",
}
LINEAGE_VARIABLES = frozenset(LINEAGE_ENV.values())
TASK_FIELDS = ("taskId", "claimEpoch", "hostTurnId")
# Closed span activity vocabulary read by the attribution report.
ACTIVITIES = ("model", "tool", "host-slot-wait", "native-queue-wait", "pressure-wait")
# Observed task handoff order (plan §7 A6); an event is evidence, never the transition.
HANDOFF_PHASES = ("dependencies-satisfied", "ready", "claim-requested", "host-accepted",
                  "execution-started", "artifact-published", "consumer-accepted",
                  "terminal-settlement")
CLAIM_PHASES = frozenset(HANDOFF_PHASES[2:])
ARTIFACT_PHASES = frozenset(("artifact-published", "consumer-accepted"))
# Identities handed over at the start marker (the approved titles and scripts).
MAX_HANDOVER = 64


def bounded_id(value: object) -> bool:
    """Accept an opaque 1-256 character printable ASCII identifier without whitespace."""
    return (isinstance(value, str) and 0 < len(value) <= MAX_ID_LENGTH and value.isascii()
            and value.isprintable() and not any(char.isspace() for char in value))


def valid_epoch(value: object) -> bool:
    """A claim epoch is a nonnegative safe integer; booleans and strings are not epochs."""
    return type(value) is int and 0 <= value <= MAX_EPOCH


def sha256_hex(value: object) -> bool:
    """Lowercase hexadecimal SHA-256 digest syntax."""
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _parse(field: str, raw: str) -> object | None:
    """Parse one environment lineage value; None means it is rejected, not defaulted."""
    if field in ("attemptNo", "claimEpoch"):
        number = int(raw) if raw.isascii() and raw.isdecimal() and len(raw) <= 16 else None
        low = 1 if field == "attemptNo" else 0
        return number if number is not None and low <= number <= MAX_EPOCH else None
    return raw if bounded_id(raw) else None


def _task_lineage(values: dict, rejected: list[str]) -> tuple[dict, list[str]]:
    """A claim epoch or host turn belongs to a task: without a valid task id both are rejected."""
    if "taskId" in values:
        return values, rejected
    orphans = [field for field in ("claimEpoch", "hostTurnId") if field in values]
    return ({key: value for key, value in values.items() if key not in orphans},
            [*rejected, *(field for field in orphans if field not in rejected)])


def _environment_lineage() -> tuple[dict, list[str]]:
    """Read inherited lineage; malformed values are named in lineageRejected, never guessed."""
    fields, rejected = {}, []
    for field, name in LINEAGE_ENV.items():
        raw = os.environ.get(name)
        if not raw:
            continue
        value = _parse(field, raw)
        if value is None:
            rejected.append(field)
        else:
            fields[field] = value
    return _task_lineage(fields, rejected)


def timing_context() -> dict:
    """Resolve explicit child lineage; label standalone execution honestly."""
    inherited, rejected = _environment_lineage()
    fields = {
        "schemaVersion": 2,
        "runId": inherited.get("runId", f"standalone:{_WRITER_ID}"),
        "attemptId": inherited.get("attemptId", _WRITER_ID),
        "attemptNo": inherited.get("attemptNo", 1),
        "writerId": f"{_WRITER_ID}:{os.getpid()}",
        "writerPid": os.getpid(),
        "clock": "process-monotonic",
    }
    parent = PARENT_SPAN.get() or inherited.get("parentSpanId")
    if parent:
        fields["parentSpanId"] = parent
    scoped = _TASK.get()
    if scoped is None:
        fields.update({key: inherited[key] for key in TASK_FIELDS if key in inherited})
    else:
        fields.update(scoped[0])
        rejected = [name for name in rejected if name not in TASK_FIELDS] + scoped[1]
    if rejected:
        fields["lineageRejected"] = rejected
    return fields


@contextlib.contextmanager
def task_scope(task_id: str, claim_epoch: int | None = None,
               host_turn_id: str | None = None) -> Iterator[None]:
    """Attribute rows and launched children to one task/claim; generic, optional metadata.

    Timing never fails work: a malformed value is dropped and named in ``lineageRejected``
    on every row of the scope (a malformed task id drops its epoch and turn too).
    """
    checks = {"taskId": (task_id, bounded_id), "claimEpoch": (claim_epoch, valid_epoch),
              "hostTurnId": (host_turn_id, bounded_id)}
    values = {key: value for key, (value, valid) in checks.items() if value is not None and valid(value)}
    rejected = [key for key, (value, _valid) in checks.items() if value is not None and key not in values]
    token = _TASK.set(_task_lineage(values, rejected))
    try:
        yield
    finally:
        _TASK.reset(token)


def timing_metadata(value: dict | None) -> dict:
    """Whitelist bounded non-content fields; reject arbitrary diagnostic payloads."""
    source = value or {}
    result = {key: source[key] for key in _TEXT_KEYS
              if isinstance(source.get(key), str) and len(source[key]) <= 128}
    for key in _NUMBER_KEYS:
        item = source.get(key)
        if (isinstance(item, (int, float)) and not isinstance(item, bool)
                and abs(item) <= 2**53 - 1):
            result[key] = item
    if source.get("activity") in ACTIVITIES:
        result["activity"] = source["activity"]
    return result


def handoff_problem(row: dict) -> str | None:
    """Name the first missing handoff field; shared by the writers and the report."""
    phase = row.get("handoffPhase")
    if phase not in HANDOFF_PHASES:
        return "unknown-handoff-phase"
    if not bounded_id(row.get("taskId")):
        return "handoff-missing-task"
    if phase in CLAIM_PHASES and not valid_epoch(row.get("claimEpoch")):
        return "handoff-missing-claim-epoch"
    if phase in ARTIFACT_PHASES and not sha256_hex(row.get("artifactSha256")):
        return "handoff-missing-artifact"
    if "hostTurnId" in row and not bounded_id(row["hostTurnId"]):
        return "handoff-invalid-host-turn"
    if "consumerId" in row and (phase != "consumer-accepted" or not bounded_id(row["consumerId"])):
        return "handoff-invalid-consumer"
    return None


def handover_problem(value: object) -> str | None:
    """Validate the handed-over identities recorded at a start marker.

    Each entry names one approved input (for example ``clip-3-title`` or ``clip-3-script``)
    by a bounded label and the SHA-256 of the exact handed-over bytes; labels are unique.
    """
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_HANDOVER:
        return f"handover must list 1-{MAX_HANDOVER} identities"
    labels = [item.get("label") for item in value if isinstance(item, dict)]
    if len(labels) != len(value) or len(set(labels)) != len(labels) or not all(map(bounded_id, labels)):
        return "handover labels must be unique bounded identifiers"
    if not all(set(item) == {"label", "sha256"} and sha256_hex(item["sha256"]) for item in value):
        return "handover entries need exactly a label and a lowercase SHA-256"
    return None


def lineage_environment() -> dict[str, str]:
    """Only the allowlisted lineage of the current span, for a closed child environment."""
    context = timing_context()
    return {name: str(context[field]) for field, name in LINEAGE_ENV.items() if field in context}


def timing_environment() -> dict[str, str]:
    """Forward the current parent span to nested Python subprocesses explicitly.

    Stale inherited lineage is replaced, so an absent parent or task is absent in the child.
    """
    inherited = {name: value for name, value in os.environ.items() if name not in LINEAGE_VARIABLES}
    return {**inherited, **lineage_environment()}
