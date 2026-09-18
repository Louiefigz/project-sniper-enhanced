"""Closed mutation and reversion authority for a picture review plan."""
from __future__ import annotations

from dataclasses import dataclass

from edit.picture_lock_common import content_hash

PLAN_FIELD = "cutRepairPicturePlanAuthority"
_HEX = frozenset("0123456789abcdef")
_KEYS = {
    "schemaVersion", "kind", "operationHash", "parentPlanObjectHash",
    "parentTimelineMapHash", "childTimelineMapHash", "target",
    "parentCutRow", "parentCutRowHash", "childCutRow", "childCutRowHash",
    "sourceExtension", "reclaimedSilence", "dirtyFrameRange",
    "mappingProof", "mappingProofHash", "reversion", "authorityHash",
}
_TARGET_KEYS = {
    "index", "segmentId", "parentElementVersion", "childElementVersion",
}
_REVERSION_KEYS = {
    "action", "index", "segmentId", "expectedChildCutRowHash",
    "restoreParentCutRowHash",
}


class PicturePlanAuthorityError(ValueError):
    """A picture plan mutation receipt is open or stale."""


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 \
        and all(char in _HEX for char in value)


def _element_version(row: object) -> int | None:
    if not isinstance(row, dict) \
            or "generation" in row and "version" in row:
        return None
    value = row.get("generation", row.get("version", 1))
    return value if type(value) is int and value > 0 else None


@dataclass(frozen=True)
class PicturePlanAuthorityInput:
    """Exact facts proved by the picture review-plan builder."""

    operation_hash: str
    parent_plan_hash: str
    index: int
    parent_row: dict
    parent_version: int
    child_row: dict
    child_version: int
    source_extension: dict
    reclaimed_silence: dict
    dirty_frame_range: dict
    parent_map_hash: str
    child_map_hash: str
    mapping_proof: dict
    mapping_proof_hash: str


def _target(value: PicturePlanAuthorityInput) -> dict:
    return {
        "index": value.index,
        "segmentId": value.parent_row["id"],
        "parentElementVersion": value.parent_version,
        "childElementVersion": value.child_version,
    }


def _reversion(value: PicturePlanAuthorityInput) -> dict:
    return {
        "action": "restore-parent-cut-row",
        "index": value.index,
        "segmentId": value.parent_row["id"],
        "expectedChildCutRowHash": content_hash(value.child_row),
        "restoreParentCutRowHash": content_hash(value.parent_row),
    }


def build_picture_plan_authority(
    value: PicturePlanAuthorityInput,
) -> dict:
    """Seal the exact row replacement and its deterministic reversion."""
    core = {
        "schemaVersion": 1,
        "kind": "cut-repair-picture-plan-authority",
        "operationHash": value.operation_hash,
        "parentPlanObjectHash": value.parent_plan_hash,
        "parentTimelineMapHash": value.parent_map_hash,
        "childTimelineMapHash": value.child_map_hash,
        "target": _target(value),
        "parentCutRow": value.parent_row,
        "parentCutRowHash": content_hash(value.parent_row),
        "childCutRow": value.child_row,
        "childCutRowHash": content_hash(value.child_row),
        "sourceExtension": value.source_extension,
        "reclaimedSilence": value.reclaimed_silence,
        "dirtyFrameRange": value.dirty_frame_range,
        "mappingProof": value.mapping_proof,
        "mappingProofHash": value.mapping_proof_hash,
        "reversion": _reversion(value),
    }
    return parse_picture_plan_authority({
        **core, "authorityHash": content_hash(core)})


def _closed_rows(core: dict) -> bool:
    target = core.get("target")
    reversion = core.get("reversion")
    return (
        isinstance(target, dict) and set(target) == _TARGET_KEYS
        and isinstance(reversion, dict) and set(reversion) == _REVERSION_KEYS
    )


def _hash_bindings(core: dict) -> bool:
    hashes = (
        "operationHash", "parentPlanObjectHash", "parentTimelineMapHash",
        "childTimelineMapHash", "parentCutRowHash", "childCutRowHash",
        "mappingProofHash",
    )
    return (
        all(_sha256(core.get(key)) for key in hashes)
        and core.get("parentCutRowHash")
        == content_hash(core.get("parentCutRow"))
        and core.get("childCutRowHash")
        == content_hash(core.get("childCutRow"))
        and core.get("mappingProofHash")
        == content_hash(core.get("mappingProof"))
    )


def _target_binding(core: dict) -> bool:
    target = core["target"]
    parent, child = core.get("parentCutRow"), core.get("childCutRow")
    parent_version = _element_version(parent)
    child_version = _element_version(child)
    return (
        type(target.get("index")) is int and target["index"] >= 0
        and isinstance(target.get("segmentId"), str)
        and bool(target["segmentId"])
        and isinstance(parent, dict) and isinstance(child, dict)
        and parent.get("id") == child.get("id") == target["segmentId"]
        and parent_version == target.get("parentElementVersion")
        and child_version == target.get("childElementVersion")
        and parent_version is not None
        and child_version == parent_version + 1
    )


def _reversion_binding(core: dict) -> bool:
    target = core["target"]
    reversion = core["reversion"]
    return (
        reversion.get("action") == "restore-parent-cut-row"
        and reversion.get("index") == target.get("index")
        and reversion.get("segmentId") == target.get("segmentId")
        and reversion.get("expectedChildCutRowHash")
        == core.get("childCutRowHash")
        and reversion.get("restoreParentCutRowHash")
        == core.get("parentCutRowHash")
    )


def parse_picture_plan_authority(value: object) -> dict:
    """Reopen one exact plan-carried mutation/reversion receipt."""
    if not isinstance(value, dict) or set(value) != _KEYS:
        raise PicturePlanAuthorityError("picture plan authority is not closed")
    core = {key: item for key, item in value.items()
            if key != "authorityHash"}
    if core.get("schemaVersion") != 1 \
            or core.get("kind") != "cut-repair-picture-plan-authority" \
            or not _closed_rows(core) \
            or not _hash_bindings(core) \
            or not _target_binding(core) \
            or not _reversion_binding(core) \
            or not _sha256(value.get("authorityHash")) \
            or value.get("authorityHash") != content_hash(core):
        raise PicturePlanAuthorityError("picture plan authority is stale")
    return dict(value)


def validate_picture_plan_authority_for_plan(
    plan: object,
) -> dict | None:
    """Require a plan-carried receipt to bind its exact child row and map."""
    if not isinstance(plan, dict):
        raise PicturePlanAuthorityError("picture plan must be an object")
    value = plan.get(PLAN_FIELD)
    if value is None:
        return None
    authority = parse_picture_plan_authority(value)
    target = authority["target"]
    track = plan.get("cutTrack")
    index = target["index"]
    if not isinstance(track, list) or index >= len(track) \
            or track[index] != authority["childCutRow"]:
        raise PicturePlanAuthorityError(
            "picture plan authority does not bind cutTrack")
    from edit.compatibility_projection import build_projection, stable_digest
    projection = build_projection(plan, stable_digest(plan))
    if projection["timelineMapHash"] != authority["childTimelineMapHash"]:
        raise PicturePlanAuthorityError(
            "picture plan authority does not bind child timeline")
    return authority
