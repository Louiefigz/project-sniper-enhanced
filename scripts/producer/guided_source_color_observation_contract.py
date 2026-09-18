"""Pure source-color observation-section validation, never cold qualification.

The caller authenticates original staging/reservation bytes and OpeningInputs.
Record types and hashes alone prove none of that provenance. No source, raw
frame metadata, filesystem, timer or callback is touched here. Project history
and admission declaredFrames are unavailable in OpeningInputs: their recorded
hash/count remain assertions until separate original parents/admission and
full-frame replay joins them. Returned JSON cannot construct an execution owner.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from color.grade_contract import closed, integer
from color.grade_project_authority import _selected_source
from cut_preview_io import digest
from guided_opening_inputs import DOCUMENTS, OpeningInputs, _INPUT_KEYS
from guided_source_color_observation_rows import (
    observation_reference, same_observation_data, validate_observation_source,
)
from guided_source_color_preparation import _snapshots, _used
from guided_source_color_staging_contract import _hash, _literal, _path, validate_source_color_staging
from ingest_execution_authority import _verify_admitted_row
from ingest_media_observation import VerifiedExecutionMedia

_SECTION = {"schemaVersion", "kind", "scope", "processInput", "opening", "parents", "sources", "elapsedMs",
            "gamutMeasured", "gradeApplied", "basePictureObserved", "openingApproved", "deliveryApproved"}
_PROCESS = {"schemaVersion", "kind", "scope", "input", "reservation", "sourceColorHash"}
_ENTRY = {"lane", "originalPath", "snapshotPath", "sha256", "sizeBytes", "mediaKind",
          "admissionReceiptPath", "admissionReceiptSha256"}


def _plans(documents: dict) -> dict:
    """Keep unsupported controls on either original plan; never strip or relabel them."""
    accepted, candidate = documents["acceptedPlan"], documents["candidatePlan"]
    for plan in (accepted, candidate):
        if type(plan) is not dict or plan.get("baselineLook") is not None or "presenterLayouts" in plan \
                or plan.get("reframe") not in (None, {}, {"strategy": "none"}):
            raise ValueError("source color observation cannot relabel a look, presenter or reframed plan")
    if type(candidate.get("target")) is not dict or candidate["target"].get("mode") != "longform":
        raise ValueError("source color observation requires its original longform target")
    same_observation_data(accepted.get("cutTrack"), candidate.get("cutTrack"))
    return accepted


def _inputs(inputs: OpeningInputs, staged: dict) -> tuple:
    """Join only actual caller-supplied original metadata, without invoking its lifetime."""
    if type(inputs) is not OpeningInputs or type(inputs.verified_media) is not VerifiedExecutionMedia \
            or type(inputs.path) is not type(Path()):
        raise ValueError("source color observation requires original opening input metadata and capture")
    value = closed(inputs.value, _INPUT_KEYS, "observation original inputs")
    _literal(value, {"schemaVersion": 1, "kind": "guided-opening-media-input"})
    refs = closed(value["documents"], DOCUMENTS, "observation original document refs")
    documents = closed(inputs.documents, DOCUMENTS, "observation original documents")
    if type(documents["authority"]) is not dict or type(documents["manifest"]) is not dict:
        raise ValueError("source color observation original authority/manifest is malformed")
    opening = staged["opening"]
    expected = {"inputPath": str(inputs.path), "inputSha256": _hash(inputs.sha256),
                "executionId": value["executionId"], "executionInputHash": value["executionInputHash"]}
    same_observation_data({key: opening[key] for key in expected}, expected)
    if value["executionInputHash"] != digest({key: row for key, row in value.items() if key != "executionInputHash"}):
        raise ValueError("source color observation original input semantic hash differs")
    same_observation_data(refs["manifest"]["sha256"], staged["expected"]["manifestSha256"])
    authority = documents["authority"]
    same_observation_data({key: authority[key] for key in ("clockHash", "generationStartedAt")},
                          {key: opening[key] for key in ("clockHash", "generationStartedAt")})
    accepted = _plans(documents)
    _snapshots(inputs.verified_media)
    entries = VerifiedExecutionMedia.entries(inputs.verified_media)
    if type(entries) is not list or not 1 <= len(entries) <= 10000:
        raise ValueError("source color observation original source entries are unbounded")
    for entry in entries:
        closed(entry, _ENTRY, "observation original source entry")
    return documents, entries, _used(accepted, staged["sourceColor"]["declarations"])


def _admission(source_id: str, current: tuple, capture: VerifiedExecutionMedia) -> tuple:
    """Match original source-lane metadata and same-pass snapshot identities, without stat."""
    documents, entries, _ids = current
    source, entry = _selected_source({"sourceId": source_id}, documents["acceptedPlan"], documents["manifest"], entries)
    closed(entry, _ENTRY, "observation original source entry")
    _literal(entry, {"lane": "source", "mediaKind": "timed-media"})
    for path in (source["path"], source["originalPath"], entry["snapshotPath"], entry["originalPath"]):
        _path(path)
    _verify_admitted_row(source, {"source"}, {entry["originalPath"]: entry}, "source color observation")
    _hash(entry["sha256"])
    _hash(entry["admissionReceiptSha256"])
    same_observation_data(entry["admissionReceiptPath"], f".sniper-external-media/receipts/{entry['admissionReceiptSha256']}.json")
    integer(entry["sizeBytes"], 1, 8 * 1024 ** 3)
    same_observation_data(source["sourceSizeBytes"], entry["sizeBytes"])
    snapshots = [row for row in capture.snapshots if row.path == entry["snapshotPath"]]
    if len(snapshots) != 1:
        raise ValueError("source color observation is missing its original source capture")
    snapshot = snapshots[0]
    same_observation_data((snapshot.sha256, snapshot.size_bytes), (entry["sha256"], entry["sizeBytes"]))
    return source, entry, snapshot


def _process(value: object, staged: dict, reservation: dict) -> None:
    """Join declared raw refs only; raw SHA authentication belongs to the later IO reader."""
    row = closed(value, _PROCESS, "observation original process input")
    _literal(row, {"schemaVersion": 1, "kind": "guided-opening-source-color-process-input",
                   "scope": "explicit-staged-input-not-observation-cleanup-or-approval"})
    observation_reference(row["input"], _path(reservation["sidecarPath"]), 8 * 1024 ** 2)
    same_observation_data(row["reservation"], staged["reservation"])
    same_observation_data(row["sourceColorHash"], digest(staged["sourceColor"]))


def validate_source_color_observations(section: object, sidecar: object, reservation: object,
                                       inputs: OpeningInputs) -> dict:
    """Return only detached validated data; no decoder, admission or base authority is added."""
    staged = validate_source_color_staging(sidecar, reservation)
    row = closed(section, _SECTION, "source color observation section")
    _literal(row, {"schemaVersion": 1, "kind": "guided-opening-source-color-observation-section",
        "scope": "actual-live-observations-not-base-consumption-or-media-approval", "gamutMeasured": False,
        "gradeApplied": False, "basePictureObserved": False, "openingApproved": False, "deliveryApproved": False})
    same_observation_data(row["opening"], staged["opening"])
    same_observation_data(row["parents"], staged["expected"])
    _process(row["processInput"], staged, reservation)
    current = _inputs(inputs, staged)
    jobs, sources = staged["jobs"], row["sources"]
    if type(sources) is not list or len(sources) != len(jobs) or tuple(job["sourceId"] for job in jobs) != current[2]:
        raise ValueError("source color observation must retain every original first-use source in order")
    total, previous_end, previous_start = integer(row["elapsedMs"], 0, 1_500_000), 0, 0
    for source, job in zip(sources, jobs):
        declaration = staged["sourceColor"]["declarations"][job["sourceId"]]
        start, end = validate_observation_source(source, (job, declaration),
            _admission(job["sourceId"], current, inputs.verified_media), total)
        if start < previous_start or start + 1 < previous_end:
            raise ValueError("source color observation sequential job timings overlap or reorder")
        previous_start, previous_end = start, end
    return deepcopy(row)
