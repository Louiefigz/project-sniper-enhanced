"""Project actual live all-source evidence, never recreate an owner from JSON.

This data-only section is for a future separate source-color media receipt. It
does not publish a file, attest base-encode consumption, read raw evidence again,
decode, convert, select or approve media. Its original staging reservation must
still be present; cold reading must use the eventual separately held archive.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from cut_preview_io import digest
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_base_context import SourceColorBaseContext, _opening
from guided_source_color_opening import _OpeningColorRead
from guided_source_color_staging_read import _held_current, _unchanged as staging_unchanged
from headless.grade_launch_files import HeldLaunchFile


def _staging(context: SourceColorBaseContext) -> object:
    """Require the original opening's exact retained staging, before callbacks."""
    if type(context) is not SourceColorBaseContext:
        raise RuntimeError("source-color observation projection requires the actual base context")
    SourceColorBaseContext.assert_metadata(context)
    owner = _opening(context)
    _held_current(owner.staging, owner.staging_origin)
    staging_unchanged(owner.staging._read)
    _OpeningColorRead.reservation_current(owner)
    return owner.staging


def _raw_reference(files: tuple, path: Path) -> dict:
    """Select one original ref; never use today's file size/hash as a new baseline."""
    matches = [row for row in files if row.path == path]
    if not matches:
        raise RuntimeError("source-color projection lacks an original held artifact")
    refs = [{"path": str(row.path), "sha256": row.sha256,
             "sizeBytes": len(row.raw) if type(row) is HeldLaunchFile else row.identity[6]} for row in matches]
    if any(not same_read_metadata(ref, hold_read_metadata(refs[0])) for ref in refs[1:]):
        raise RuntimeError("source-color projection has conflicting original artifact refs")
    return refs[0]


def _artifacts(completed: object, files: tuple, staged: dict) -> dict:
    """Retain actual post-observation refs together with original preflight refs."""
    directory = completed.result_path.parent
    paths = {"input": directory / "input.json", "implementation": directory / "implementation.json",
             "launchClaim": directory / "launch-claim.json", "parents": directory / "parents.json",
             "execution": directory / "execution/execution.json", "probe": directory / "execution/result/probe.json",
             "frames": directory / "execution/result/frames.ffprobe", "observation": completed.result_path}
    refs = {key: _raw_reference((*files, *completed.files), path) for key, path in paths.items()}
    for key in ("input", "implementation", "launchClaim"):
        if not same_read_metadata(refs[key], hold_read_metadata(staged[key])):
            raise RuntimeError("source-color projection original job differs from staged raw refs")
    return refs


def _source_rows(context: SourceColorBaseContext, staged: object) -> list[dict]:
    """Preserve unique first-use order and actual supplied-record evidence types."""
    holder, batch = context.source_color, context.source_color.batch
    preflight = batch._preflight
    files = tuple(row for row, _expected in preflight._read.retained if type(row) is HeldLaunchFile)
    jobs = staged.value["jobs"]
    if len(jobs) != len(batch.preparation.jobs):
        raise RuntimeError("source-color projection omitted original used-source jobs")
    result = []
    rows = zip(batch.preparation.jobs, batch.observations, holder.observations, batch.timings, jobs)
    for prepared, observed, identity, timing, job in rows:
        metadata, record = prepared.record(), observed.observation
        if job["sourceId"] != prepared.binding.source_id or identity.completed is not observed \
                or timing.source_id != job["sourceId"] or observed.context.source is not prepared.source:
            raise RuntimeError("source-color projection changed actual source/observation order")
        stream = record.records.stream
        result.append({"sourceId": job["sourceId"], "jobId": job["jobId"],
            "selection": deepcopy(staged.value["sourceColor"]["declarations"][job["sourceId"]]),
            "source": {"path": prepared.source.path, "sha256": prepared.source.sha256,
                       "sizeBytes": prepared.source.size_bytes}, "binding": metadata["binding"],
            "artifacts": _artifacts(observed, files, job),
            "records": {"policy": record.records.validator_policy, "sha256": record.records.records_sha256,
                        "decodedFrames": record.records.decoded_record_count, "firstPts": stream.first_pts,
                        "timeBase": str(stream.time_base), "stepTicks": stream.step_ticks,
                        "width": stream.width, "height": stream.height},
            "bt709Identity": asdict(identity.metadata), "timing": {"sourceId": timing.source_id,
                "startedMs": timing.started_ms, "elapsedMs": timing.elapsed_ms,
                "status": timing.status, "cleanupVerified": timing.cleanup_verified}})
    return result


def project_source_color_observations(context: SourceColorBaseContext) -> dict:
    """Return detached real live metadata, explicitly NOT a durable media proof."""
    staged = _staging(context)
    original = staged._origin
    SourceColorBaseContext.assert_current(context)
    if _staging(context) is not staged:
        raise RuntimeError("source-color projection replaced its original staging")
    files = tuple(row for row, _value in staged._read.loaded)
    sidecar = _raw_reference(files, staged._read.reference[0])
    source_color = staged.value["sourceColor"]
    result = {"schemaVersion": 1, "kind": "guided-opening-source-color-observation-section",
        "scope": "actual-live-observations-not-base-consumption-or-media-approval",
        "processInput": {"schemaVersion": 1, "kind": "guided-opening-source-color-process-input",
            "scope": "explicit-staged-input-not-observation-cleanup-or-approval", "input": sidecar,
            "reservation": deepcopy(staged.value["reservation"]), "sourceColorHash": digest(source_color)},
        "opening": deepcopy(staged.value["opening"]), "parents": deepcopy(staged.value["expected"]),
        "sources": _source_rows(context, staged), "elapsedMs": context.source_color.batch.elapsed_ms,
        "gamutMeasured": False, "gradeApplied": False, "basePictureObserved": False,
        "openingApproved": False, "deliveryApproved": False}
    expected = hold_read_metadata(result)
    SourceColorBaseContext.assert_current(context)
    _held_current(staged, original)
    if _staging(context) is not staged:
        raise RuntimeError("source-color projection replaced its original staging")
    if not same_read_metadata(result, expected):
        raise RuntimeError("source-color observation projection changed during final callback")
    SourceColorBaseContext.assert_metadata(context)
    return result
