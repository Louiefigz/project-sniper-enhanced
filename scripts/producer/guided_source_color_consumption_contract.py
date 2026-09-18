"""Strict cold picture-consumption joins; command strings remain DATA ONLY.

Original worker provenance is supplied by the enclosing authenticated evidence
reader. Cut part elementary hashes remain retained execution attestations, not
new decodes. Only the separate native packet-copy reader observes current video.
"""
from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path

from color.grade_contract import integer
from cut_preview_io import digest
from cut_manifestation_authority import _expected_part
from cross_runtime_canonical_json import canonical_compact_json
from fingerprints import plan_content_hash
from guided_opening_inputs import closed, hash_value
from guided_source_color_consumption_records import bounded_timeline, command, join_manifestation, metadata_size
from guided_source_color_observation_rows import same_observation_data as equal
from guided_source_color_staging_contract import _literal, _path

CONSUMPTION_SCOPE = "actual-picture-command-consumption-not-color-or-quality-approval"
EVIDENCE_SCOPE = "actual-source-observation-and-picture-consumption-not-color-or-quality-approval"


def evidence_contract(evidence: dict, bindings: dict) -> tuple:
    """Close supplied section/reference scopes before selecting any file or native input."""
    closed(bindings, {"evidenceRef", "fullProgram", "observations", "outputRoot", "tools"}, "consumption bindings")
    closed(evidence, {"schemaVersion", "kind", "scope", "observations", "pictureConsumption", "fullProgram",
        "gamutMeasured", "gradeApplied", "colorQualified", "openingApproved", "deliveryApproved", "receiptHash"}, "source evidence")
    _literal(evidence, {"schemaVersion": 1, "kind": "guided-opening-source-color-media-evidence", "scope": EVIDENCE_SCOPE,
        "gamutMeasured": False, "gradeApplied": False, "colorQualified": False, "openingApproved": False, "deliveryApproved": False})
    equal(evidence["observations"], bindings["observations"])
    equal(evidence["receiptHash"], digest({key: row for key, row in evidence.items() if key != "receiptHash"}))
    reference = closed(bindings["evidenceRef"], {"path", "sha256", "sizeBytes", "receiptHash"}, "source evidence ref")
    equal(reference["receiptHash"], evidence["receiptHash"])
    consumed = closed(evidence["pictureConsumption"], {"scope", "cuts", "manifestation", "master", "pictureCopy",
        "colorQualified", "deliveryApproved", "basePublication"}, "source consumption")
    _literal(consumed, {"scope": CONSUMPTION_SCOPE, "colorQualified": False, "deliveryApproved": False})
    metadata_size(consumed, 8 * 1024 ** 2)
    full = closed(evidence["fullProgram"], {"base", "cutManifestation", "timelineMap", "sourceFloatMaster"}, "consumption full program")
    equal(full["base"], bindings["fullProgram"]["base"])
    for name in ("cutManifestation", "timelineMap"):
        equal(full[name], bindings["fullProgram"]["receipts"][name])
    return consumed, full


def _argv(row: dict, source: str) -> None:
    """Validate bounded retained argv joins but never interpret it as executable authority."""
    argv = command(row["argv"])
    if argv[-1] != row["outputPath"] or source not in argv:
        raise RuntimeError("cold consumption recorded argv differs from original input/output")


def _sources(observations: dict, inputs: object, expected: list[str]) -> dict:
    """Join every first-use source to original independently replayed source/admission metadata."""
    rows = observations["sources"]
    if type(rows) is not list or [row["sourceId"] for row in rows] != list(dict.fromkeys(expected)):
        raise RuntimeError("cold consumption original source order or coverage differs")
    manifest = {row["id"]: row for row in inputs.documents["manifest"]["sources"]}
    result = {}
    for row in rows:
        source, binding, selected = row["source"], row["binding"], manifest[row["sourceId"]]
        equal((source["path"], source["sha256"], source["sizeBytes"]),
              (selected["path"], selected["sourceSha256"], selected["sourceSizeBytes"]))
        equal(binding["sourceSha256"], source["sha256"])
        equal(binding["admissionReceiptSha256"], selected["admissionReceiptSha256"])
        result[row["sourceId"]] = {"path": str(_path(source["path"])), "sha256": hash_value(source["sha256"]),
            "admissionReceiptSha256": hash_value(binding["admissionReceiptSha256"]),
            "declarationSha256": hash_value(binding["declarationSha256"])}
    return result


def _cut(row: dict, expected: tuple, original: tuple) -> int:
    """Require exact repeated compiler occurrence, original profile and cumulative frames."""
    segment, source, before = expected
    authority, base = original
    closed(row, {"segment", "sourcePath", "outputPath", "framesBefore", "profile", "source", "argv", "frames"}, "consumed cut")
    # The recorder is canonical JSON; the compiler's on-disk floats stay distinct.
    equal(row["segment"], json.loads(canonical_compact_json(segment)))
    equal(row["source"], source)
    equal(row["sourcePath"], source["path"])
    equal(row["outputPath"], str(base / "work/cut-parts" / f"part_{segment['index']:04d}.mp4"))
    equal(row["framesBefore"], before)
    rate = Fraction(authority["frameRate"])
    equal(row["profile"], {**authority["target"], "frameRate": f"{rate.numerator}/{rate.denominator}", "pixelFormat": "yuv420p"})
    _argv(row, source["path"])
    return integer(row["frames"], 1, 72000)


def _master(row: dict, authority: dict, paths: tuple) -> None:
    """Keep exact post-cut input, sole picture-master output and the original frame clock."""
    base, picture = paths
    closed(row, {"inputPath", "outputPath", "ass", "fps", "fpsExact", "duration", "frameCount", "cover", "argv"}, "consumed master")
    rate, count = Fraction(authority["frameRate"]), authority["totalFrames"]
    fps = round(float(rate))
    equal((row["inputPath"], row["outputPath"], row["ass"], row["cover"]),
          (str(base / "work/mezzanine.mp4"), str(picture), None, None))
    equal((row["fps"], row["frameCount"]), (fps, count))
    if (rate == fps and row["fpsExact"] is not None) or (rate != fps and
            (type(row["fpsExact"]) is not str or Fraction(row["fpsExact"]) != rate)):
        raise RuntimeError("cold consumption master exact frame rate changed")
    if type(row["duration"]) not in (int, float) or not math.isfinite(row["duration"]) \
            or row["duration"] != count / float(rate):
        raise RuntimeError("cold consumption master duration changed")
    _argv(row, row["inputPath"])


def _manifest_types(record: dict, timeline: dict) -> None:
    """Close JSON scalar loopholes around the legacy mathematical manifestation verifier."""
    for part, segment in zip(record["parts"], timeline["segments"]):
        equal(part, _expected_part(segment, part))
    concat = record["concat"]
    for key in ("videoFrames", "videoElementaryBytes", "orderedPartsVideoBytes"):
        integer(concat[key], 1, 2 ** 53 - 1)
    proof = closed(record["durationProof"], {"videoDuration", "expectedDuration", "videoFrames", "driftFrames",
        "toleranceFrames", "segments"}, "cut duration proof")
    equal(proof["videoFrames"], concat["videoFrames"])
    equal(proof["segments"], len(timeline["segments"]))


def validate_consumption_plan(consumed: dict, records: dict, context: object) -> None:
    """Recompile complete ordered cuts; reuse existing exact elementary/frame proof joins."""
    documents, bindings = context.inputs.documents, context.bindings
    plan, authority = documents["candidatePlan"], documents["authority"]
    equal(plan["cutTrack"], documents["acceptedPlan"]["cutTrack"])
    # render.compile_stage and write_manifestation use ordinary json.dump.
    timeline = bounded_timeline(plan, authority)
    equal(records["timelineMap"], timeline)
    segments, cuts = timeline["segments"], consumed["cuts"]
    if type(cuts) is not list or len(cuts) != len(segments):
        raise RuntimeError("cold consumption cut occurrence coverage differs")
    sources = _sources(bindings["observations"], context.inputs, [row["source_id"] for row in segments])
    base = Path(bindings["outputRoot"]) / "full-program-base"
    before = 0
    for row, segment in zip(cuts, segments):
        before += _cut(row, (segment, sources[segment["source_id"]], before), (authority, base))
    equal(before, authority["totalFrames"])
    joined = join_manifestation(records["cutManifestation"], (plan, timeline, cuts, tuple(row["outputPath"] for row in cuts)))
    _manifest_types(records["cutManifestation"], timeline)
    joined["concatPath"] = str(base / "work/mezzanine.mp4")
    equal(consumed["manifestation"], json.loads(canonical_compact_json(joined)))
    equal(joined["concat"]["videoFrames"], authority["totalFrames"])
    if Fraction(joined["frameRate"]) != Fraction(authority["frameRate"]):
        raise RuntimeError("cold consumption manifestation frame rate changed")
    _master(consumed["master"], authority, (base, Path(consumed["basePublication"]["receiptPath"]).parent / "picture-master.mp4"))


def validate_publication(consumed: dict, records: dict, context: object) -> None:
    """Bind original final-base sealed semantics to current source-bus and candidate plan."""
    publication = closed(consumed["basePublication"], {"receiptPath", "receipt"}, "base publication")
    record, bus = records["sourceFloatMaster"], records["sourceBus"]
    closed(record, {"schemaVersion", "kind", "approved", "audioClockPolicy", "busReceiptHash", "masteringPolicyVersion",
        "planHash", "path", "sha256", "picture", "audioClock", "filter", "delivery", "audiblePathAacEncodes",
        "legacyPictureTransportAacStillExecuted", "receiptHash"}, "ordinary source-float master")
    _literal(record, {"schemaVersion": 2, "kind": "ordinary-source-float-master", "approved": False,
        "audioClockPolicy": "source-float-v2", "audiblePathAacEncodes": 1, "legacyPictureTransportAacStillExecuted": True})
    equal(record, publication["receipt"])
    equal(record["receiptHash"], digest({key: row for key, row in record.items() if key != "receiptHash"}))
    equal(bus["receiptHash"], digest({key: row for key, row in bus.items() if key != "receiptHash"}))
    equal(record["busReceiptHash"], bus["receiptHash"])
    equal(record["planHash"], plan_content_hash(context.inputs.documents["candidatePlan"]))
    equal((bus["kind"], bus["audioClockPolicy"], bus["planHash"]),
          ("ordinary-source-float-bus", "source-float-v2", record["planHash"]))
    base = context.bindings["fullProgram"]["base"]
    equal((record["path"], record["sha256"], record["picture"]), (base["path"], base["sha256"], consumed["pictureCopy"]))
    proof = closed(consumed["pictureCopy"], {"picturePacketsIdentical", "picturePackets", "pictureTimeBase", "pictureSourceSha256"}, "picture copy")
    _literal(proof, {"picturePacketsIdentical": True})
    equal(proof["picturePackets"], context.inputs.documents["authority"]["totalFrames"])
    hash_value(proof["pictureSourceSha256"])
