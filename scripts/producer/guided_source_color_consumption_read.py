"""Cold base-picture consumption replay beneath authenticated source evidence.

This is a finite retained read lifetime, NOT execution/adoption/lease authority.
The enclosing reader authenticates observations, full-program/result refs and
original tools, holds the protected phase timer and pins PATH to its ffprobe.
Recorded argv is never executed. Existing packet probes inspect only generated
picture-master/final-base files; no source hashes/decoders or new clocks occur.
Part elementary hashes remain original-worker attestations; parts may be gone.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
from pathlib import Path

from audio.audio_mix_picture import observe_picture_source, verify_picture_copy
from cross_runtime_canonical_json import canonical_compact_json
from cut_manifestation_authority import MANIFESTATION_NAME, verify_manifestation
from cut_preview_io import MAX_MEDIA
from guided_opening_inputs import closed, hash_value
from guided_source_color_consumption_contract import evidence_contract, validate_consumption_plan, validate_publication
from guided_source_color_consumption_files import ConsumptionReadFiles, SourceColorConsumptionReadContext
from guided_source_color_observation_rows import same_observation_data as equal
from guided_source_color_staging_contract import _path

_JSON_LIMIT = 16 * 1024 ** 2
HeldSourceColorConsumption = ConsumptionReadFiles


def _role(reference: dict, expected: Path, maximum: int) -> tuple:
    """Exact raw-ref paths choose roles; metadata never selects an arbitrary video input."""
    if type(reference) is not dict or Path(_path(reference["path"])) != expected:
        raise RuntimeError("cold consumption artifact escaped its exact original role")
    hash_value(reference["sha256"])
    if "sizeBytes" in reference and (type(reference["sizeBytes"]) is not int or not 0 < reference["sizeBytes"] <= maximum):
        raise RuntimeError("cold consumption artifact size exceeds its role bound")
    return expected, maximum


def _references(read: ConsumptionReadFiles, consumed: dict, full: dict) -> dict:
    """Select all original finite files before the first arbitrary source/tool callback."""
    bindings, inputs = read.context.bindings, read.context.inputs
    root = Path(_path(bindings["outputRoot"]))
    opening = bindings["observations"]["opening"]
    equal((opening["inputPath"], opening["inputSha256"], opening["executionId"], opening["executionInputHash"]),
          (str(inputs.path), inputs.sha256, inputs.value["executionId"], inputs.value["executionInputHash"]))
    equal(str(root), str(Path(_path(opening["claimPath"])).parent / "media-output"))
    base = root / "full-program-base"
    refs = {"evidence": bindings["evidenceRef"], **full, "sourceBus": bindings["fullProgram"]["receipts"]["sourceBus"]}
    bus = Path(_path(refs["sourceBus"]["path"]))
    if bus.name != "bus-receipt.json" or bus.parent.parent != base or not bus.parent.name.startswith(".source-float-v2-"):
        raise RuntimeError("cold consumption original source bus has the wrong base role")
    publication = closed(consumed["basePublication"], {"receiptPath", "receipt"}, "consumed publication")
    equal(publication["receiptPath"], str(bus.parent / "master-receipt.json"))
    refs["pictureMaster"] = {"path": str(bus.parent / "picture-master.mp4"),
                             "sha256": hash_value(consumed["pictureCopy"]["pictureSourceSha256"])}
    expected = {"evidence": root / "source-color-evidence.json", "base": base / "final.mp4",
        "timelineMap": base / "timeline_map.json", "cutManifestation": base / MANIFESTATION_NAME,
        "sourceFloatMaster": bus.parent / "master-receipt.json", "sourceBus": bus,
        "pictureMaster": bus.parent / "picture-master.mp4"}
    for name, reference in refs.items():
        read.capture(*_role(reference, expected[name], MAX_MEDIA if name in {"base", "pictureMaster"} else _JSON_LIMIT))
    if sum(row.identity[6] for row in read.files.values() if row.maximum == _JSON_LIMIT) > 64 * 1024 ** 2:
        raise RuntimeError("cold consumption aggregate metadata exceeds 64MiB")
    read.capture(Path(read.tool["path"]), 512 * 1024 ** 2)
    return refs


def _metadata_records(read: ConsumptionReadFiles, refs: dict) -> dict:
    """Authenticate exact raw metadata once and retain every actual parser return."""
    evidence = read.load(refs["evidence"])
    equal(evidence, read.evidence)
    records = {name: read.load(refs[name]) for name in ("timelineMap", "cutManifestation", "sourceFloatMaster", "sourceBus")}
    # The actual ordinary master sealer uses compact canonical bytes WITHOUT a newline.
    expected = canonical_compact_json(records["sourceFloatMaster"]).encode("utf8")
    equal(refs["sourceFloatMaster"]["sha256"], hashlib.sha256(expected).hexdigest())
    equal(refs["sourceFloatMaster"]["sizeBytes"], len(expected))
    return records


def _observe(read: ConsumptionReadFiles, refs: dict, consumed: dict) -> None:
    """Use actual existing packet observation/copy proof, never a PictureSource from JSON."""
    authority = read.context.inputs.documents["authority"]
    read.check()
    read.verify_hash(refs["base"])
    read.verify_hash(refs["pictureMaster"])
    read.check()
    source = observe_picture_source(refs["pictureMaster"]["path"],
        float(Fraction(authority["totalFrames"], 1) / Fraction(authority["frameRate"])), refs["pictureMaster"]["sha256"])
    read.retain_picture(source)
    read.check()
    proof = verify_picture_copy(source, refs["base"]["path"])
    read.retain(proof)
    read.check()
    equal(proof, consumed["pictureCopy"])
    equal((source.path, source.sha256, len(source.packets)),
          (refs["pictureMaster"]["path"], refs["pictureMaster"]["sha256"], authority["totalFrames"]))


def hold_source_color_consumption(evidence: dict, context: SourceColorConsumptionReadContext) -> ConsumptionReadFiles:
    """Return retained original file/native metadata checks, never execution or approval authority."""
    read = ConsumptionReadFiles(evidence, context)
    consumed, full = evidence_contract(evidence, context.bindings)
    refs = _references(read, consumed, full)
    records = _metadata_records(read, refs)
    validate_consumption_plan(consumed, records, context)
    validate_publication(consumed, records, context)
    read.check()
    actual = read.retain(verify_manifestation(str(Path(context.bindings["outputRoot"]) / "full-program-base"),
                                            context.inputs.documents["candidatePlan"]))
    equal(actual, records["cutManifestation"])
    read.check()
    _observe(read, refs, consumed)
    read.finish(deepcopy(consumed))
    read.check()
    return read


def read_source_color_consumption(evidence: dict, context: SourceColorConsumptionReadContext) -> dict:
    """Convenience detached-data read; enclosing multi-stage callers must retain the hold instead."""
    held = hold_source_color_consumption(evidence, context)
    held.assert_metadata()
    return held.record
