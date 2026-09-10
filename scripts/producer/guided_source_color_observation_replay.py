"""One-pass cold frame metadata replay and exact historical project joins.

Original raw worker metadata is read evidence only. No decoded source, owner,
phase clock, installed-tool scan or approval is created by this module.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from color.deadline import require_time
from color.grade_bt709_identity import validate_bt709_identity_records
from color.grade_contract import closed, integer
from color.grade_observation_profile import V1, project_profile
from color.grade_observation_read import _lines
from guided_source_color_observation_execution import artifact, validate_recorded_execution
from guided_source_color_observation_pins import PROJECT_ROOTS, STAGED_ROOTS, recorded_inventory
from guided_source_color_observation_rows import _ARTIFACTS, same_observation_data as same

OBSERVATION_FIELDS = {"schemaVersion", "policy", "jobId", "inputSha256", "status", "cleanupVerified", "cleanupMs",
    "workerPhaseMs", "replayMs", "gradeApplicable", "deliveryApproved", "parentsSha256", "observation",
    "implementation", "elapsedMs", "artifactHash"}
_CAVEAT = "Ingest declaredFrames/exact manifest frameRate are candidates until full original EOF/metadata/cadence replay matches."


def _job_input(documents: dict, context: tuple, pins: dict) -> None:
    """Use historical parent PID as metadata, never require today's process parent."""
    row, job, staged, reservation = context
    value = documents["input"]
    if project_profile(value) is not V1:
        raise ValueError("cold source color cannot relabel a non-V1 job")
    same(value, {"schemaVersion": 1, "policy": V1.project_policy, "jobId": job["jobId"],
        "producerDir": staged["producerDir"], "sourceId": row["sourceId"], "declaration": row["selection"]["declaration"],
        "expected": staged["expected"], "ownerPid": reservation["ownerPid"],
        "implementationSha256": job["implementation"]["sha256"]})
    inventory = closed(documents["implementation"], {"files"}, "cold staged implementation")
    staged_files = recorded_inventory(inventory["files"], pins, STAGED_ROOTS)
    claim = {"schemaVersion": 1, "kind": "owned-grade-launch-claim",
        "scope": "preclaimed-source-observation-not-recovery-or-approval", "jobId": job["jobId"],
        "inputPath": job["inputPath"], "inputSha256": job["input"]["sha256"], "executionDir": job["executionDir"],
        "sourcePath": row["source"]["path"], "sourceSha256": row["binding"]["sourceSha256"],
        "frameCount": row["binding"]["frameCount"], "profile": None, "containerName": job["containerName"],
        "openingClaimPath": staged["opening"]["claimPath"], "openingClaimSha256": staged["opening"]["claimSha256"],
        "runtime": reservation["runtime"]}
    same(documents["launchClaim"], claim)
    for name in ("executionSources", "implementation"):
        values = documents["execution"] if name == "executionSources" else documents["observation"]
        if any(staged_files.get(item["path"]) != item["sha256"] for item in values[name]):
            raise ValueError("cold original worker inventory differs from staged raw pins")


def _parents(value: dict, row: dict, prepared: dict, context: tuple) -> None:
    """Recompute history/admission/count joins from original raw current saved parents."""
    inputs, staged, project = context
    manifest = inputs.documents["manifest"]
    matches = [source for source in manifest["sources"] if source["id"] == row["sourceId"]]
    if len(matches) != 1:
        raise ValueError("cold original manifest source is ambiguous")
    same(prepared["binding"], row["binding"])
    same(value, {"binding": prepared["binding"], "declaration": prepared["declaration"],
        "sourcePath": prepared["sourcePath"], "sourceManifestRow": matches[0],
        "sourceSetAdmission": manifest.get("sourceSetAdmission"), "expectedParents": staged["expected"],
        "projectHistory": {"projectSha256": staged["expected"]["projectSha256"], "history": project.get("history", [])},
        "clockCaveat": _CAVEAT})
    facts = prepared["admissionExpectation"]["decoded"]["facts"]
    same({key: row["records"][key] for key in ("width", "height", "decodedFrames")},
         {"width": facts["width"], "height": facts["height"], "decodedFrames": facts["declaredFrames"]})


def _timed_lines(read: object, lines: Iterator[str]) -> Iterator[str]:
    """Charge every metadata line to the original read deadline, without guard recursion."""
    for line in lines:
        require_time(read.deadline)
        yield line


def record_projection(records: object) -> dict:
    """Small exact normalized projection; raw frame bytes are not serialized again."""
    stream = records.stream
    return {"policy": records.validator_policy, "sha256": records.records_sha256,
        "decodedFrames": records.decoded_record_count, "firstPts": stream.first_pts,
        "timeBase": str(stream.time_base), "stepTicks": stream.step_ticks, "width": stream.width, "height": stream.height}


def _replay(read: object, row: dict, documents: dict, worker: dict) -> None:
    """Reuse the actual strict V1/full-SAR/EOF parser once, never a live-owner factory."""
    read.check()
    lines = _lines(Path(row["artifacts"]["frames"]["path"]), worker["decoder"])
    try:
        result = validate_bt709_identity_records((row["binding"], row["selection"]["declaration"], documents["probe"]),
                                                _timed_lines(read, lines), worker["decoder"])
    finally:
        lines.close()
    actual = record_projection(result.records)
    read.retain(actual)
    same(actual, row["records"])
    same(asdict(result.metadata), row["bt709Identity"])
    read.check()


def _observation(documents: dict, row: dict, pins: dict) -> None:
    """Bind immutable project summary to actual replayed records and original raw refs."""
    value, execution = documents["observation"], documents["execution"]
    artifact(value, OBSERVATION_FIELDS)
    expected = {"schemaVersion": 1, "policy": V1.project_policy, "jobId": row["jobId"],
        "inputSha256": row["artifacts"]["input"]["sha256"], "status": "complete", "cleanupVerified": True,
        "gradeApplicable": False, "deliveryApproved": False, "parentsSha256": row["artifacts"]["parents"]["sha256"],
        "cleanupMs": execution["cleanupMs"]}
    same({key: value[key] for key in expected}, expected)
    records, refs = row["records"], row["artifacts"]
    summary = {key: records[key] for key in ("decodedFrames", "firstPts", "timeBase", "stepTicks", "width", "height")}
    summary.update(source=row["binding"], recordsSha256=records["sha256"], rawFramesSha256=refs["frames"]["sha256"],
                   executionSha256=refs["execution"]["sha256"], decodedFrameFlagsAvailable=False,
                   gradeApplicable=False, deliveryApproved=False)
    same(value["observation"], summary)
    recorded_inventory(value["implementation"], pins, PROJECT_ROOTS)
    elapsed = integer(value["elapsedMs"], 0, 120001)
    phase = integer(value["workerPhaseMs"], 0, elapsed + 1)
    replay = integer(value["replayMs"], 0, elapsed + 1)
    if phase + replay > elapsed + 1 or execution["elapsedMs"] > phase + 1 \
            or elapsed > row["timing"]["elapsedMs"] + 1:
        raise ValueError("cold original project timing differs from sequential recorded work")


def replay_observation_job(read: object, context: tuple, prepared: object, pins: dict) -> None:
    """Read one already-held job and compare every normalized and original-parent join."""
    row, job, staged, reservation, project = context
    documents = {name: read.load(row["artifacts"][name]) for name in _ARTIFACTS if name != "frames"}
    intent_path = str(Path(job["executionDir"]) / "launch-intent.json")
    documents["intent"] = read.load({"path": intent_path, "sha256": documents["execution"]["launchIntentSha256"],
                                     "sizeBytes": read.files[intent_path].identity[6]})
    read.check()
    _parents(documents["parents"], row, prepared.record(), (read.context.inputs, staged, project))
    _job_input(documents, (row, job, staged, reservation), pins)
    worker = validate_recorded_execution(documents, row, job, pins)
    _observation(documents, row, pins)
    _replay(read, row, documents, worker)
