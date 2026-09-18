"""Closed body source replay envelopes; syntax never creates a replay capability.

Worker fields come only from the actual registered work's completed readers.
Cold receipt identity is structural until it is compared with a new actual
replay on the caller's original body clock. No grade or approval is granted.
"""
from __future__ import annotations

from copy import deepcopy

from cut_preview_io import digest
from guided_body_inputs import BodyControl
from guided_body_source_color_replay import validate_body_source_color_replay
from guided_body_source_color_work import body_source_color_readback, REPLAY_STAGES
from guided_body_work import BodyWork
from guided_opening_inputs import closed, hash_value
from guided_source_color_observation_rows import same_observation_data as same

READBACK_SCOPE = "exact-source-color-held-private-body-media-not-body-or-delivery-approval"
REPLAY_SCOPE = "original-opening-observation-and-base-consumption-not-new-grade-or-approval"
SOURCE_KEYS = {"sourceColorReplay", "sourceColorReadback"}
FALSE_FLAGS = {"gamutMeasured", "gradeApplied", "colorQualified", "bodyApproved", "deliveryApproved"}


def _projection(value: object, control: BodyControl) -> dict:
    """Validate only exact original evidence metadata and explicitly limited flags."""
    row = closed(value, {"schemaVersion", "kind", "scope", "sourceColorEvidence",
        "observationRecordHash", "consumptionRecordHash", "sourceColorRecordsReplayed",
        "basePictureConsumptionVerified"} | FALSE_FLAGS, "body source replay projection")
    expected = {"schemaVersion": 1, "kind": "guided-body-original-source-color-replay",
        "scope": REPLAY_SCOPE, "sourceColorRecordsReplayed": True,
        "basePictureConsumptionVerified": True, **dict.fromkeys(FALSE_FLAGS, False)}
    for key, value in expected.items():
        same(row[key], value)
    same(row["sourceColorEvidence"], control.documents["openingResult"]["sourceColorEvidence"])
    for key in ("observationRecordHash", "consumptionRecordHash"):
        hash_value(row[key])
    return deepcopy(row)


def _fields(value: dict, control: BodyControl) -> dict:
    """Keep V1 closed and require both replay fields for an explicitly source2 body."""
    version = control.value["schemaVersion"]
    if type(version) is not int or version not in (1, 2):
        raise RuntimeError("body source result requires an explicit supported version")
    if version == 1:
        if SOURCE_KEYS.intersection(value) or "sourceColorReplay" in control.value \
                or control.documents["openingResult"].get("schemaVersion") == 2:
            raise RuntimeError("body source result cannot downgrade to legacy")
        return {"schemaVersion": 1}
    replay = validate_body_source_color_replay(value["sourceColorReplay"])
    same(replay, control.value["sourceColorReplay"])
    return {"schemaVersion": 2, "sourceColorReplay": replay,
            "sourceColorReadback": _projection(value["sourceColorReadback"], control)}


def _stages(value: object) -> None:
    """Require both unique actual replay phases without replacing existing work stages."""
    if type(value) is not list or not 1 <= len(value) <= 2048:
        raise RuntimeError("body source result work stages are outside the bounded class")
    names = []
    for row in value:
        if type(row) is not dict or row.get("status") != "complete" \
                or type(row.get("stage")) is not str or type(row.get("elapsedMs")) is not int \
                or not 0 <= row["elapsedMs"] <= 3_300_000:
            raise RuntimeError("body source result stage failed or has invalid elapsed work")
        names.append(row["stage"])
    if any(names.count(name) != 1 for name in REPLAY_STAGES) \
            or names.index(REPLAY_STAGES[0]) >= names.index(REPLAY_STAGES[1]):
        raise RuntimeError("body source result lacks ordered original replay phases")


def body_source_result_identity(record: dict, control: BodyControl) -> dict:
    """Structural receipt join only; the later actual bridge must reproduce its hashes."""
    fields = _fields(record, control)
    if fields["schemaVersion"] == 2:
        _stages(record["stages"])
    return fields


def body_source_result_fields(work: BodyWork) -> dict:
    """Only the actual private work can project successful original replay groups."""
    projection = body_source_color_readback(work)
    if projection is None:
        return _fields({}, work.control)
    fields = _fields({"sourceColorReplay": work.control.value["sourceColorReplay"],
                      "sourceColorReadback": projection}, work.control)
    BodyWork.guard(work)
    return fields


def recheck_body_source_result(record: dict, work: BodyWork) -> dict:
    """Compare the held receipt with actual completed readers, not self-reported flags."""
    fields = body_source_result_fields(work)
    for key, value in fields.items():
        if digest(record[key]) != digest(value):
            raise RuntimeError("body result source replay differs from actual original replay")
    BodyWork.guard(work)
    return fields
