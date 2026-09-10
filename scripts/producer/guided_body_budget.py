"""Recheck retained original body allocation without creating a fresh deadline."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from guided_body_contract import body_timestamp
from guided_body_execution import BodyExecutionClock
from guided_body_inputs import BodyControl, _same
from guided_opening_inputs import closed

BODY_POLICY = {"version": 1, "basis": "declared-engineering-allocation-not-measured-throughput",
    "requestMs": 7_200_000, "wholeAttemptMs": 3_300_000, "requiredFinishReserveMs": 1_500_000,
    "preparedAssetCreditMs": 0, "scope": "body-admission-not-calibrated-throughput-or-complete-request-accounting"}
_ADMISSION = {"schemaVersion", "kind", "policy", "clockHash", "generationStartedAt", "observedAt",
    "requestDeadlineAt", "phaseDeadlineAt", "elapsedRequestWallMs", "remainingBodyPhaseWallMs", "admitted",
    "reason", "attemptDeadlineAt", "excludedUserWaitMs"}


def _milliseconds(value: object) -> int:
    """Use exact serialized milliseconds; no parent monotonic epoch is restored."""
    return round(body_timestamp(value).timestamp() * 1000)


def _stamp(value: int) -> str:
    """Match the controller's canonical UTC millisecond projection."""
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _admission(control: BodyControl) -> tuple[dict, int]:
    """Check all policy arithmetic and explicitly retain charged human wait."""
    row = closed(control.documents["budgetAdmission"], _ADMISSION, "body budget admission")
    activation = control.activation
    origin = _milliseconds(activation["generationStartedAt"])
    observed = _milliseconds(row["observedAt"])
    request_end = origin + BODY_POLICY["requestMs"]
    phase_end = request_end - BODY_POLICY["requiredFinishReserveMs"]
    if observed < origin or phase_end - observed < BODY_POLICY["wholeAttemptMs"]:
        raise RuntimeError("body retained admission had no full declared allocation")
    expected = {"schemaVersion": 1, "kind": "guided-body-deadline-admission", "policy": BODY_POLICY,
        "clockHash": activation["clockHash"], "generationStartedAt": activation["generationStartedAt"],
        "observedAt": row["observedAt"], "requestDeadlineAt": _stamp(request_end),
        "phaseDeadlineAt": _stamp(phase_end), "elapsedRequestWallMs": observed - origin,
        "remainingBodyPhaseWallMs": phase_end - observed, "admitted": True,
        "reason": "within-declared-allocation", "attemptDeadlineAt": _stamp(observed + BODY_POLICY["wholeAttemptMs"]),
        "excludedUserWaitMs": None}
    _same(row, expected, "retained original budget admission")
    return row, observed


def bind_body_budget(control: BodyControl, clock: BodyExecutionClock) -> None:
    """Bound current work by the exact original retained admission and live remainder."""
    admission, observed = _admission(control)
    claim = control.documents["admissionClaim"]
    row = closed(control.documents["budgetPrecommit"], {"schemaVersion", "kind", "clockHash", "observedAt",
        "elapsedMs", "remainingMs", "state"}, "body budget precommit")
    at, created = _milliseconds(row["observedAt"]), _milliseconds(claim["createdAt"])
    deadline, elapsed = _milliseconds(admission["attemptDeadlineAt"]), row["elapsedMs"]
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) \
            or not at - observed <= elapsed < BODY_POLICY["wholeAttemptMs"] or not observed <= at <= created < deadline:
        raise RuntimeError("body retained precommit elapsed/clock is invalid")
    expected = {"schemaVersion": 1, "kind": "guided-body-deadline-observation", "clockHash": control.activation["clockHash"],
        "observedAt": row["observedAt"], "elapsedMs": elapsed,
        "remainingMs": math.floor(BODY_POLICY["wholeAttemptMs"] - elapsed), "state": "within-deadline"}
    _same(row, expected, "retained body precommit")
    clock.bind_wall(deadline, _milliseconds(control.activation["createdAt"]))
