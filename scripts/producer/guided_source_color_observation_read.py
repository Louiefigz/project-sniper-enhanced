"""Cold authenticated-reference observation replay, returning DATA ONLY.

The caller supplies the actual stopped V3/final-cleanup references, original
OpeningInputs capture and authenticated executed pipeline/lock. It must verify
that original pipeline current/snapshot closure; data types alone prove none
of that provenance. Only the exact archived reservation is read: active.json,
current processes, tools and original source bytes are never opened here.
Original-worker network/decoder/cleanup claims remain historical attestations;
this replay adds no source decoder, live owner, gamut/grade/base/media approval.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from weakref import WeakKeyDictionary

from color.grade_contract import closed
from guided_opening_claim import _KEYS, _identity
from guided_source_color_observation_contract import validate_source_color_observations
from guided_source_color_observation_files import ColdObservationRead, ColdSourceColorObservationContext
from guided_source_color_observation_pins import APPROVAL, WORKER, pipeline_inventory
from guided_source_color_observation_replay import replay_observation_job
from guided_source_color_observation_rows import _ARTIFACTS, observation_reference, same_observation_data as same
from guided_source_color_preparation import SourceColorParentRefs, SourceColorPreparationContext, prepare_source_color_jobs
from guided_source_color_staging_contract import _hash, _path, _uuid, validate_source_color_staging

_HELD_READS = WeakKeyDictionary()


@dataclass(frozen=True, init=False, eq=False)
class HeldColdSourceColorObservations:
    """Finite original-file READ evidence only; no live source or cleanup authority."""

    record: dict
    scope: ClassVar[str] = "cold-observation-file-lifetime-not-execution-or-approval"

    def assert_metadata(self) -> None:
        """Callback-free final files/data/cutoff sweep, never a new replay or work guard."""
        read = _original_read(self)
        ColdObservationRead.metadata(read)
        _original_read(self)

    def check(self) -> None:
        """Check the original guard/files/cutoff without replaying metadata or hashing source."""
        read = _original_read(self)
        ColdObservationRead.check(read)
        HeldColdSourceColorObservations.assert_metadata(self)


def _original_read(value: HeldColdSourceColorObservations) -> ColdObservationRead:
    """Authenticate the exact finite holder before touching its privately retained reader."""
    if type(value) is not HeldColdSourceColorObservations or value not in _HELD_READS:
        raise RuntimeError("cold observation lifetime requires its actual original read")
    read, record = _HELD_READS[value]
    if set(vars(value)) != {"record"} or value.record is not record:
        raise RuntimeError("cold observation original returned record changed")
    return read


def _reference(read: ColdObservationRead, path: Path, sha: str) -> dict:
    """A raw SHA is independently held; the initial size only bounds this read."""
    return {"path": str(path), "sha256": _hash(sha), "sizeBytes": read.files[str(path)].identity[6]}


def _locations(read: ColdObservationRead) -> tuple:
    """Derive canonical original top files before any arbitrary callback or JSON read."""
    refs, inputs = read.context.references, read.context.inputs
    closed(refs, {"sidecar", "reservation", "archive", "producerDir", "openingClaim", "implementation"}, "cold refs")
    claim = closed(refs["openingClaim"], _KEYS, "cold original opening claim")
    producer = Path(_path(refs["producerDir"]))
    execution = producer / "guided-v2-operations" / _uuid(claim["requestId"]) / "executions" / _uuid(claim["executionId"])
    _identity(claim, inputs.value, (inputs.path, inputs.sha256, execution / "media-output"))
    observation_reference(refs["sidecar"], execution / "source-color/input.json", 8 * 1024 ** 2)
    active = _path(refs["reservation"]["path"])
    if active.name != "active.json" or active.parent.name != ".sniper-color-resource":
        raise ValueError("cold original reservation namespace differs")
    observation_reference(refs["reservation"], active, 8 * 1024 ** 2)
    archive = _path(refs["archive"]["path"])
    _uuid(archive.parent.name, True)
    if archive != execution / "cleanup-attempts" / archive.parent.name / "reservation.json":
        raise ValueError("cold reservation archive escaped its original execution")
    same(refs["archive"], {**refs["reservation"], "path": str(archive)})
    return producer, execution


def _initial(read: ColdObservationRead) -> tuple:
    """Authenticate top refs without caller callbacks; all child baselines follow first."""
    producer, execution = _locations(read)
    refs, inputs = read.context.references, read.context.inputs
    expected = read.retain(pipeline_inventory(inputs, refs["implementation"]))
    pipeline = inputs.value["pipeline"]
    approval = refs["implementation"]["imageApproval"]
    observation_reference(approval, _path(pipeline["snapshotRoot"]) / APPROVAL, 1024 ** 2)
    paths = ((Path(refs["sidecar"]["path"]), 8 * 1024 ** 2), (Path(refs["archive"]["path"]), 8 * 1024 ** 2),
             (inputs.path, 128 * 1024), (execution / "execution-claim.json", 128 * 1024),
             (Path(pipeline["lockPath"]), 16 * 1024 ** 2), (Path(approval["path"]), 1024 ** 2),
             (Path(pipeline["snapshotRoot"]) / WORKER, 128 * 1024))
    for path, maximum in paths:
        read.capture(path, maximum)
    sidecar, reservation = read.load(refs["sidecar"]), read.load(refs["archive"])
    staged = read.retain(validate_source_color_staging(sidecar, reservation))
    same(staged["reservation"], refs["reservation"])
    same(read.section["processInput"]["input"], refs["sidecar"])
    same(read.load(_reference(read, inputs.path, inputs.sha256)), inputs.value)
    claim_ref = _reference(read, execution / "execution-claim.json", staged["opening"]["claimSha256"])
    claim = read.load(claim_ref)
    same(claim, refs["openingClaim"])
    opening = {"claimPath": claim_ref["path"], "claimSha256": claim_ref["sha256"],
        **{key: claim[key] for key in ("inputPath", "inputSha256", "executionId", "executionInputHash",
                                     "clockHash", "generationStartedAt", "budgetAdmissionHash", "beforeJournalHash")}}
    same(staged["opening"], opening)
    same(reservation["runtime"], claim["runtime"])
    same(staged["producerDir"], str(producer))
    same(read.load(_reference(read, Path(pipeline["lockPath"]), pipeline["lockSha256"])), refs["implementation"]["pipelineLock"])
    image = read.load(approval)
    same({key: image[key] for key in ("schemaVersion", "imageId")}, {"schemaVersion": 1, "imageId": claim["runtime"]["imageId"]})
    same(approval["sha256"], claim["runtime"]["imageApprovalSha256"])
    same(approval["path"], claim["runtime"]["imageApprovalPath"])
    same(claim["runtime"]["runtimeRepoRoot"], pipeline["snapshotRoot"])
    same(approval["sha256"], expected[approval["path"]])
    worker = Path(pipeline["snapshotRoot"]) / WORKER
    raw = read.raw(_reference(read, worker, expected[str(worker)]))
    pins = read.retain({"expected": expected, "snapshot": pipeline["snapshotRoot"],
        "runtime": claim["runtime"], "approval": image, "worker": raw.decode("utf8", errors="strict")})
    return staged, reservation, pins


def _capture_children(read: ColdObservationRead, staged: dict) -> None:
    """Hold all jobs, intents and saved parent/admission records before first guard."""
    producer = Path(staged["producerDir"])
    for row in read.section["sources"]:
        for name, (_relative, maximum) in _ARTIFACTS.items():
            read.capture(Path(row["artifacts"][name]["path"]), maximum)
        read.capture(Path(row["artifacts"]["execution"]["path"]).parent / "launch-intent.json", 128 * 1024)
    for path in (producer / "edit_plan.json", producer / "asset_manifest.json", producer.parent / "project.json"):
        read.capture(path, 2 * 1024 ** 2)
    used = {row["source"]["path"] for row in read.section["sources"]}
    for entry in read.context.inputs.verified_media.entries():
        if entry["lane"] == "source" and entry["snapshotPath"] in used:
            read.capture(producer / entry["admissionReceiptPath"], 4 * 1024 ** 2)


def hold_source_color_observations(section: dict, context: ColdSourceColorObservationContext) -> HeldColdSourceColorObservations:
    """Replay once and retain original files through later caller-owned read phases."""
    read = ColdObservationRead(section, context)
    staged, reservation, pins = _initial(read)
    validated = read.retain(validate_source_color_observations(section, staged, reservation, context.inputs))
    _capture_children(read, staged)
    read.check()
    producer = Path(staged["producerDir"])
    preparation = SourceColorPreparationContext(SourceColorParentRefs(producer, staged["expected"]), read.deadline, read.check)
    jobs = prepare_source_color_jobs(context.inputs, staged["sourceColor"]["declarations"], preparation)
    if type(jobs) is not tuple or len(jobs) != len(validated["sources"]):
        raise ValueError("cold source color preparation omitted original sources")
    records = [read.retain(job.record()) for job in jobs]
    read.check()
    project = read.load(_reference(read, producer.parent / "project.json", staged["expected"]["projectSha256"]))
    for row, job, prepared, record in zip(validated["sources"], staged["jobs"], jobs, records):
        same(prepared.record(), record)
        replay_observation_job(read, (row, job, staged, reservation, project), prepared, pins)
    result = read.retain(deepcopy(validated))
    held = object.__new__(HeldColdSourceColorObservations)
    object.__setattr__(held, "record", result)
    _HELD_READS[held] = (read, result)
    HeldColdSourceColorObservations.check(held)
    return held


def read_source_color_observations(section: dict, context: ColdSourceColorObservationContext) -> dict:
    """Preserve the data-only API; no retained lifetime or new authority escapes it."""
    return hold_source_color_observations(section, context).record
