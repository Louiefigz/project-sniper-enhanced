"""Opt-in ordinary assembly using retained source dialogue and one full master."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from audio.program_master_bus import build_program_master, verify_program_master
from audio.program_master_delivery import deliver_program_master
from audio.program_master_reuse import PROGRAM_AUDIO_POINTER, select_program_master
from audio.assemble_picture_reuse import picture_reuse_input_hash, reuse_final_picture
from audio.assemble_publication import (CAPTION_SHARD_NAME, stage_caption_shards, copy_verified as _copy_support,
    optional_hash as _optional_hash, publish_files, require_settled)
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, audio_policy_reason
from audio.render_audio_cache import load_source_bus
from audio.held_program_preparation import (HeldProgramPreparation,
    assert_held_program_preparation, load_held_program_preparation, preparation_reuse_evidence)
from audit.audit_render import run_audit, write_reports, report_to_dict, render_markdown
from cut_delivery_authority import DELIVERY_NAME, seal_assembled_delivery
from cut_manifestation_authority import MANIFESTATION_NAME
from cut_manifestation_authority import _receipt_hash
from cut_preview_io import bound_json, file_hash, read_bytes, real_directory, write_new
from fingerprints import plan_content_hash, write_assembled_sidecar
from preview_proxy import write_proxy
from graphics.owned_execution import current as current_owned_graphics

_INPUT_NAMES = ("timeline_map.json", "cover.png", MANIFESTATION_NAME, DELIVERY_NAME,
                "geometry_predictions.json", ".sniper-learning/geometry_residuals.jsonl")
_OUTPUT_NAMES = ("graphics_placements.json", "caption_authority.json", "caption_compilation.json",
    "caption_shards.json", "caption_palmier.json", "caption_chapters.json", "captions.ass",
    "captions.srt", "chapters.txt", ".caption-free-composite.mp4", ".caption-free-composite.json")


@dataclass(frozen=True)
class _AssemblyCandidate:
    """Held caller outputs and inputs, with a retained isolated working layout."""

    job: Any
    directory: Path
    plan_sha256: str
    before: dict[str, str | None]
    inputs: dict[str, str]
    preparation: HeldProgramPreparation | None = None


@dataclass(frozen=True)
class _QualifiedCandidate:
    """Same complete candidate audio/video and support that actually passed QC."""

    report: Any
    support: dict[str, str]


def _copy_input(source: Path, destination: Path) -> str:
    """Copy one exact bounded regular input into the candidate, never a symlink."""
    raw = read_bytes(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(raw)
    return file_hash(destination)


def _stage(job: Any, preparation: HeldProgramPreparation | None = None) -> _AssemblyCandidate:
    """Snapshot only known render dependencies without touching public outputs."""
    if job.audio_clock_policy != SOURCE_FLOAT_POLICY_V2 or not job.plan_path:
        raise RuntimeError("source-float assembly requires explicit v2 policy and held plan path")
    reason = audio_policy_reason(job.plan, SOURCE_FLOAT_POLICY_V2)
    if reason:
        raise RuntimeError(reason)
    plan_path = Path(job.plan_path).absolute()
    if plan_content_hash(bound_json(plan_path)) != plan_content_hash(job.plan):
        raise RuntimeError("source-float assembly plan differs from current canonical bytes")
    root = Path(job.out).absolute().parent
    require_settled(root)
    names = set(_OUTPUT_NAMES) | set(_support_hashes(root)) | {
        Path(job.out).name, Path(job.out).name + ".assembled.json", DELIVERY_NAME,
        "audit_report.json", "audit_report.md", PROGRAM_AUDIO_POINTER}
    if preparation:
        names.update(name for name in _INPUT_NAMES if "/" not in name)
    before = {str(root / name): _optional_hash(root / name) for name in names}
    directory = Path(tempfile.mkdtemp(prefix=".source-assembly-v2-", dir=root))
    inputs = {}
    source_root = preparation.root if preparation else root
    for name in _INPUT_NAMES:
        source = source_root / name
        if source.exists():
            inputs[str(source)] = _copy_input(source, directory / name)
    if preparation and any(expected != preparation.support.get(source) for source, expected in inputs.items()):
        raise RuntimeError("held program preparation support changed while copying")
    if preparation:
        inputs.update(preparation.support)
    if preparation is None and getattr(job, "owned_graphics", None) is None \
            and isinstance(job.plan.get("captionsTrack"), dict):
        stage_caption_shards(root, directory, before)
    write_new(directory / "edit_plan.json", job.plan)
    return _AssemblyCandidate(job, directory, file_hash(plan_path), before, inputs, preparation)


def _assert_held(candidate: _AssemblyCandidate) -> None:
    """Reject plan, output, or calibration races before any public replacement.

    The original public hold and the later input holds are checked separately so a
    later hold can never shadow the original one."""
    if file_hash(Path(candidate.job.plan_path).absolute()) != candidate.plan_sha256:
        raise RuntimeError("source-float assembly plan changed during candidate execution")
    holds = [*candidate.before.items(), *candidate.inputs.items()]   # checked separately, never merged
    for path, expected in holds:
        if _optional_hash(Path(path)) != expected:
            raise RuntimeError("source-float assembly held inputs or public outputs changed")


def _conflicts(candidate: _AssemblyCandidate, path: str, expected: str) -> str | None:
    """Name the original hold a later hold would contradict, if any."""
    if candidate.before.get(path, expected) != expected:
        return "public"
    if candidate.inputs.get(path, expected) != expected:
        return "input"
    return None


def _hold(candidate: _AssemblyCandidate, held: dict[str, str]) -> _AssemblyCandidate:
    """Add later holds; a path already held with a different hash is a conflict, never an override."""
    for path, expected in held.items():
        label = _conflicts(candidate, path, expected)
        if label:
            raise RuntimeError(f"held program input conflicts with the original {label} hold")
    return replace(candidate, inputs={**candidate.inputs, **held})


def _staged_job(candidate: _AssemblyCandidate) -> Any:
    """Own imported graphics writes inside this new attempt, never caller cache."""
    job = replace(candidate.job, out=str(candidate.directory / "final.mp4"))
    if candidate.preparation is None:
        return job
    real_directory(candidate.directory)
    cache = candidate.directory / "graphics-cache"
    cache.mkdir(mode=0o700)
    return replace(job, cache_dir=str(cache))


def _private_audit(candidate: _AssemblyCandidate, output: str) -> _QualifiedCandidate:
    """Audit the entire actual candidate, not a selected still or PCM proxy."""
    write_assembled_sidecar(output, candidate.job.plan)
    lineage = seal_assembled_delivery(candidate.job.base, output, candidate.job.plan, SOURCE_FLOAT_POLICY_V2)
    if lineage is None:
        raise RuntimeError("source-float assembly omitted exact cut delivery lineage")
    support = _support_hashes(candidate.directory)
    report = _run_candidate_audit(candidate)
    write_reports(report)
    if report.exit_code or report.overall == "fail":
        raise RuntimeError(f"source-float assembly full Audit B failed; retained {candidate.directory}")
    if _support_hashes(candidate.directory) != support:
        raise RuntimeError("source-float support changed during whole-output QC")
    return _QualifiedCandidate(report, support)


def _run_candidate_audit(candidate: _AssemblyCandidate) -> Any:
    """Bind the actual graphics-free base across QC without copying large media."""
    if not candidate.job.plan.get("graphicsTrack"):
        return run_audit(str(candidate.directory))
    base = Path(candidate.job.base).absolute()
    before = file_hash(base)
    if candidate.preparation and before != candidate.preparation.selection.event["baseSha256"]:
        raise RuntimeError("source-float visual QC base differs from held preparation")
    report = run_audit(str(candidate.directory), graphics_reference=str(base))
    if file_hash(base) != before:
        raise RuntimeError("source-float visual QC base changed during whole-output audit")
    return report


def _support_hashes(directory: Path) -> dict[str, str]:
    """Observe exact known support files, including every generated caption shard."""
    names = set(_OUTPUT_NAMES)
    names.update(path.name for path in directory.iterdir()
                 if CAPTION_SHARD_NAME.fullmatch(path.name))
    return {name: file_hash(directory / name) for name in sorted(names) if (directory / name).exists()}


def _program_pointer(candidate: _AssemblyCandidate, master: Any, qualified: _QualifiedCandidate, delivery: dict) -> dict:
    """Describe the selected full-program master without issuing approval."""
    return {"schemaVersion": 2, "kind": "ordinary-program-audio-pointer",
        "audioClockPolicy": SOURCE_FLOAT_POLICY_V2, "finalSha256": qualified.report.final_sha256,
        "programMasterReceiptPath": delivery["programMasterReceiptPath"],
        "programMasterReceiptHash": delivery["programMasterReceiptHash"],
        "audioProgramInputHash": master.receipt["audioProgramInputHash"],
        "pictureReuseInputHash": picture_reuse_input_hash(candidate.job, master.source_bus),
        "pictureSupportSha256": qualified.support}


def _publication_entries(candidate: _AssemblyCandidate, qualified: _QualifiedCandidate, pointer: dict) -> dict:
    """Prepare path-only rebinding and all report bytes privately before writing."""
    source, job = candidate.directory / "final.mp4", candidate.job
    metadata = candidate.directory / "publication-metadata"
    metadata.mkdir()
    report = replace(qualified.report, out_dir=str(Path(job.out).absolute().parent), final_path=os.path.abspath(job.out))
    lineage = bound_json(candidate.directory / DELIVERY_NAME)
    lineage["finalArtifact"]["path"] = os.path.abspath(job.out)
    lineage["receiptHash"] = _receipt_hash(lineage)
    write_new(metadata / DELIVERY_NAME, lineage)
    write_new(metadata / PROGRAM_AUDIO_POINTER, pointer)
    write_new(metadata / "audit_report.json", {**report_to_dict(report), "measuredCandidatePath": str(source),
        "pathRebinding": "same-sha256-after-complete-candidate-audit"})
    (metadata / "audit_report.md").write_text(render_markdown(report))
    entries = {name: (candidate.directory / name, sha) for name, sha in qualified.support.items()}
    if candidate.preparation:
        entries.update({name: (candidate.directory / name, file_hash(candidate.directory / name))
            for name in _INPUT_NAMES if "/" not in name and name != DELIVERY_NAME
            and (candidate.directory / name).exists()})
    entries.update({path.name: (path, file_hash(path)) for path in metadata.iterdir()})
    sidecar = candidate.directory / "final.mp4.assembled.json"
    entries[Path(job.out).name + ".assembled.json"] = (sidecar, file_hash(sidecar))
    entries[Path(job.out).name] = (source, qualified.report.final_sha256)
    return entries


def _candidate_current(candidate: _AssemblyCandidate, master: Any, qualified: _QualifiedCandidate) -> None:
    """Recheck immutable render inputs even between individual public replacements."""
    current_owned_graphics(candidate.job)
    if file_hash(Path(candidate.job.plan_path).absolute()) != candidate.plan_sha256:
        raise RuntimeError("source-float assembly plan changed during publication")
    if candidate.preparation:
        assert_held_program_preparation(candidate.preparation)
        _assert_imported_support(candidate)
    verify_program_master(master, candidate.job.plan)
    if file_hash(candidate.directory / "final.mp4") != qualified.report.final_sha256:
        raise RuntimeError("source-float candidate changed between audit and promotion")
    if _support_hashes(candidate.directory) != qualified.support:
        raise RuntimeError("source-float support changed after whole-output QC")
    current_owned_graphics(candidate.job)


def _assert_imported_support(candidate: _AssemblyCandidate) -> None:
    """Reject changed copied proof before/through publication, without re-sealing it."""
    preparation = candidate.preparation
    assert preparation is not None
    for name in _INPUT_NAMES:
        expected = preparation.support.get(str(preparation.root / name))
        if expected is not None and name != DELIVERY_NAME \
                and file_hash(candidate.directory / name) != expected:
            raise RuntimeError("held program preparation copied support changed")


def _publish(candidate: _AssemblyCandidate, master: Any, qualified: _QualifiedCandidate, delivery: dict) -> dict:
    """Publish only prepared exact bytes; failed ordinary writes restore originals."""
    job = candidate.job
    _assert_held(candidate)
    _candidate_current(candidate, master, qualified)
    pointer = _program_pointer(candidate, master, qualified, delivery)
    entries = _publication_entries(candidate, qualified, pointer)
    _assert_held(candidate)
    publish_files(Path(job.out).absolute().parent, entries, candidate.before,
                  lambda: _candidate_current(candidate, master, qualified))
    provenance = bound_json(Path(job.out + ".assembled.json").absolute())
    from revision_ledger import record_render, record_audit
    record_render(job.out, job.plan, provenance)
    record_audit(job.out, qualified.report.final_sha256, report_to_dict(qualified.report))
    return {"out": job.out, "planHash": provenance["planHash"], "authorityHash": provenance["authorityHash"],
        "audioClockPolicy": SOURCE_FLOAT_POLICY_V2, "programAudio": pointer,
        "programDeliveryReceipt": {"path": delivery["deliveryReceiptPath"], "receiptHash": delivery["deliveryReceiptHash"]},
        "delivery": delivery["delivery"], "audit": qualified.report.overall}


def assemble_source_audio(job: Any) -> dict:
    """Run the existing compositor/caption stages on an isolated v2 candidate."""
    from assemble import BaseManifest, _assemble_captioned, _base_state
    preparation = load_held_program_preparation(job)
    if _base_state(job.base, job.plan, job.fingerprint_path,
                   BaseManifest(job.manifest, SOURCE_FLOAT_POLICY_V2)) != "current":
        raise RuntimeError("source-float assembly requires a current v2 base; request --auto-base")
    if not job.manifest:
        raise RuntimeError("source-float assembly requires its admitted source manifest")
    manifest = bound_json(Path(job.manifest).absolute())
    manifest["_path"] = os.path.abspath(job.manifest)
    directory = os.path.dirname(os.path.abspath(job.fingerprint_path or job.base))
    bus = (preparation.selection.master.source_bus if preparation else
           load_source_bus(job.plan, manifest, (directory, job.base), job.source_bus_receipt_hash))
    candidate = _stage(job, preparation)
    staged_job = _staged_job(candidate)
    reused, held = reuse_final_picture(job, bus, candidate.directory)
    candidate = _hold(candidate, held)
    summary = ({"pictureReusedForAudioRevision": True} if reused else _assemble_captioned(staged_job))
    master, master_reused, held_master = select_program_master(job, bus, preparation, build_program_master)
    candidate = _hold(candidate, held_master)
    delivery = deliver_program_master(master, job.plan, (staged_job.out, staged_job.out),
                                      candidate.directory if preparation else None)
    report = _private_audit(candidate, staged_job.out)
    published = _publish(candidate, master, report, delivery)
    proxy = write_proxy(job.out)
    if proxy:
        published["proxy"] = proxy["path"]
    reuse = {"preparationReuse": preparation_reuse_evidence(preparation)} if preparation else {}
    return {**summary, **published, **reuse, "programMasterReused": master_reused}
