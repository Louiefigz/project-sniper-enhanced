"""Inert TEST-only metadata, never authentic decoded-media/cleanup evidence."""
from __future__ import annotations

import json
from pathlib import Path

from _grade_contract_fixture import binding, declaration
from color.grade_observation_profile import V2, V2_PROFILE
from color.grade_observation_read import _ARGS, _EXACT_VERSION
from cut_preview_io import digest, file_hash, write_new
from test_grade_frame_adapter import decoder_terminal, observed_probe, raw_frame, text_frame


def v2_context(count: int = 3) -> tuple[dict, dict, dict, list[dict]]:
    """Synthetic UHD raw records retain exact NTSC origin/ticks and explicit siting."""
    context = declaration(count)
    context.update(schemaVersion=2, sourceProfile="unknown", historyState="unknown")
    source = binding(context)
    rows = [raw_frame(index, source) for index in range(count)]
    video = observed_probe(source)["streams"][0]
    fields = {"width": 3840, "height": 2160, "color_transfer": "iec61966-2-4",
              "chroma_location": "left", "sample_aspect_ratio": "1:1"}
    for row in rows:
        row.update(fields)
    video.update(fields, codec_name="h264")
    return source, context, {"streams": [video]}, rows


def v2_request(count: int = 3) -> dict:
    """Explicit new version, without paths/limits chosen by request data."""
    return {"schemaVersion": 2, "profile": V2_PROFILE, "sourceSha256": "a" * 64,
            "frameCount": count, "timeoutSeconds": 1200}


def v2_project(fixture) -> None:
    """Adapt only an owned inert legacy TEST fixture; admission remains stubbed."""
    fixture.value.update(schemaVersion=2, policy=V2.project_policy, profile=V2_PROFILE)
    fixture.value["declaration"].update(schemaVersion=2, sourceProfile="unknown", historyState="unknown")
    receipt = fixture.producer / fixture.entry["admissionReceiptPath"]
    facts = {"mediaKind": "timed-media", "videoStreams": 1, "streamCount": 3, "declaredFrames": 180,
             "sizeBytes": 10_280_473_262, "width": 3840, "height": 2160}
    receipt.write_text(json.dumps({"decoded": {"facts": facts}, "testOnly": True}))
    fixture.entry["admissionReceiptSha256"] = file_hash(receipt)
    fixture.manifest({"sourceSizeBytes": facts["sizeBytes"],
        "admissionReceiptPath": fixture.entry["admissionReceiptPath"],
        "admissionReceiptSha256": fixture.entry["admissionReceiptSha256"]})
    (fixture.job / "input.json").write_text(json.dumps(fixture.value))


def retained_test_execution(directory: Path) -> tuple[dict, tuple, dict]:
    """Real private files with explicitly supplied metadata; no decoder was run."""
    source, declaration_row, probe, rows = v2_context()
    result_dir = directory / "result"
    result_dir.mkdir(mode=0o700)
    write_new(result_dir / "probe.json", probe)
    raw = "".join(line for row in rows for line in text_frame(row))
    (result_dir / "frames.ffprobe").write_text(raw)
    request = {**v2_request(), "sourceSha256": source["sourceSha256"]}
    args = list(_ARGS)
    args[5] = "4"
    worker = {"schemaVersion": 2, "policy": V2.policy, **V2.evidence(), "request": request,
        "status": "complete", "gradeApplicable": False, "deliveryApproved": False,
        "decodedFrameFlagsAvailable": False, "invocation": {"executable": "/usr/bin/ffprobe", "args": args},
        "timing": {}, "sourceBeforeSha256": source["sourceSha256"], "sourceAfterSha256": source["sourceSha256"],
        "tool": {"version": _EXACT_VERSION, "sha256": "d" * 64},
        "probe": {"sha256": file_hash(result_dir / "probe.json"), "bytes": (result_dir / "probe.json").stat().st_size},
        "decoder": {**decoder_terminal(3), "bytes": len(raw.encode()), "sha256": file_hash(result_dir / "frames.ffprobe")}}
    held = {"schemaVersion": 2, "policy": V2.policy, **V2.evidence(), "request": request,
        "requestHash": digest(request), "status": "complete", "cleanupVerified": True,
        "gradeApplicable": False, "deliveryApproved": False, "launchAttempted": True,
        "removal": {"canonicalAbsenceProved": True}, "sourceBeforeSha256": source["sourceSha256"],
        "sourceAfterSha256": source["sourceSha256"], "executionSources": [], "imageId": "TEST-only",
        "worker": worker, "testOnlyNotExecutionProof": True}
    held["artifactHash"] = digest(held)
    write_new(directory / "execution.json", held)
    approval = {"imageId": "TEST-only", "probedClosure": {"sha256": {"/usr/bin/ffprobe": "d" * 64}}}
    return held, (source, declaration_row), approval
