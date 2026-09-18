"""Read an actual privately returned opening, never choose one from a directory.

The server supplies both result hashes from the stopped owned worker and must
separately verify its exact current journal, lease, deadline and Docker cleanup.
Self-computed hashes are not execution authority. This command is read-only and
its successful return grants neither opening nor delivery approval.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from audio.program_master_excerpt import _owned_directory, read_master_audio
from audio.program_master_selection import read_master_selection, revalidate_master_selection
from cut_preview_io import bound_json, digest, file_hash
from cut_manifestation_authority import MANIFESTATION_NAME
from guided_opening_claim import HeldOpeningClaim, read_execution_claim
from guided_opening_execution import OpeningExecutionClock, opening_clock
from guided_opening_frames import executable_frames
from guided_opening_inputs import OpeningInputs, PROFILE, closed, hash_value, observe_inputs, read_current_inputs
from guided_opening_pipeline import observe_pipeline
from guided_opening_result import check_held_artifacts, held_ref, read_graphics, read_ranges
from palmier.process_deadline import use_process_deadline
from guided_presenter_intake import current_manual_profile as manual_profile
from guided_presenter_intake import is_presenter_profile
from guided_short_geometry import verify_short_geometry
from guided_caption_profile import caption_full_fields, caption_screen_fields
from guided_caption_integration import read_prepared_captions, assert_opening_caption_layers

SCOPE = "private-opening-media-not-opening-body-or-delivery-approval"


@dataclass(frozen=True)
class ReadAuthority:
    """Separately held values from the actual owned invocation and completion."""

    input_sha256: str
    claim_path: Path
    claim_sha256: str
    receipt_sha256: str
    receipt_hash: str


def _record(root: Path, held: ReadAuthority) -> dict:
    """Never accept an orphan, failed, self-selected or substituted result."""
    _owned_directory(root)
    if os.path.lexists(root / "media-failed.json"):
        raise RuntimeError("opening media attempt failed; any result is unselectable")
    record = bound_json(root / "media-result.json", hash_value(held.receipt_sha256))
    body = {key: value for key, value in record.items() if key != "receiptHash"}
    if record.get("receiptHash") != hash_value(held.receipt_hash) or digest(body) != held.receipt_hash:
        raise RuntimeError("opening result differs from actual held completion")
    return record


def _identity(record: dict, inputs: OpeningInputs, claim: HeldOpeningClaim, source_color: bool = False) -> None:
    """Require exact input/claim identity and explicitly limited mechanical scope."""
    expected = {"schemaVersion": 2 if source_color else 1, "kind": "guided-opening-media-result", "scope": SCOPE,
        "status": "complete", "profile": inputs.value.get("profile", PROFILE), "executionId": inputs.value["executionId"],
        "inputPath": str(inputs.path), "inputSha256": inputs.sha256,
        "executionInputHash": inputs.value["executionInputHash"],
        "executionClaim": {"path": str(claim.path), "sha256": claim.sha256},
        "authority": inputs.documents["authority"], "documents": inputs.value["documents"],
        "openingApproved": False, "deliveryApproved": False, "bodyGraphicsPrepared": False,
        "creativeVisualReview": "not-run", "subjectiveListening": "not-run",
        "qualificationScope": "private-mechanical-frame-audio-and-runtime-evidence-only",
        "processGroupCleanup": "requires-owned-server-observation"}
    closed(record, set(expected) | {"pipeline", "fullProgram", "audio", "graphics", "pictures", "media",
                                   "stages", "receiptHash"} | ({"sourceColorEvidence"} if source_color else set())
                                   | caption_screen_fields(inputs.value.get("profile")), "opening result")
    if any(type(record[key]) is not type(value) or digest(record[key]) != digest(value)
           for key, value in expected.items()):
        raise RuntimeError("opening result identity, approval scope or original authority differs")


def _full_program(record: dict, inputs: OpeningInputs, root: Path) -> tuple:
    """Reopen only the actual invocation-held event and its unchanged global bus."""
    full = closed(record["fullProgram"], {"base", "fullBaseElapsedMs", "fullProgramMasterElapsedMs", "baseReport",
        "fullBasePrepared", "bodyGraphicsPrepared", "baseAudibleTrackNotSelected", "legacyPictureTransportAacStillExecuted",
        "receipts", "fullMasterSelectionEventPath", "fullMasterSelectionEventSha256"}
        | ({"shortGeometry", "shortGeometryElapsedMs"} if manual_profile(inputs.value.get("profile")) else set())
        | caption_full_fields(inputs.value.get("profile")), "opening full-program result")
    if full["fullBasePrepared"] is not True or full["bodyGraphicsPrepared"] is not False \
            or full["baseAudibleTrackNotSelected"] is not True or full["legacyPictureTransportAacStillExecuted"] is not True:
        raise RuntimeError("opening full-program preparation scope differs")
    base = root / "full-program-base"
    held_ref(full["base"], root, base / "final.mp4")
    event = held_ref({"path": full["fullMasterSelectionEventPath"],
                      "sha256": full["fullMasterSelectionEventSha256"]}, base)
    selection = read_master_selection(event, full["fullMasterSelectionEventSha256"])
    verify_short_geometry(full, inputs, base, selection)
    bus, authority = selection.master.source_bus, inputs.documents["authority"]
    if Fraction(bus.frame_rate) != Fraction(authority["frameRate"]) or bus.frames != authority["totalFrames"]:
        raise RuntimeError("opening whole master differs from the original exact frame clock")
    refs = inputs.value["documents"]
    if selection.context.artifact_root != base or selection.context.base_path != base / "final.mp4" \
            or selection.context.plan_path != Path(refs["candidatePlan"]["path"]) \
            or selection.context.manifest_path != Path(refs["manifest"]["path"]) \
            or selection.event["planSha256"] != refs["candidatePlan"]["sha256"] \
            or selection.event["manifestSha256"] != refs["manifest"]["sha256"]:
        raise RuntimeError("opening full master is not this exact candidate/source invocation")
    paths = {"sourceBus": Path(selection.master.source_bus.directory) / "bus-receipt.json",
        "programMaster": Path(selection.master.directory) / "master-receipt.json", "masterSelection": event,
        "cutManifestation": base / MANIFESTATION_NAME, "timelineMap": base / "timeline_map.json"}
    closed(full["receipts"], set(paths), "opening full-program receipts")
    for name, path in paths.items():
        held_ref(full["receipts"][name], root, path)
    held_ref(record["audio"], root, root / "audio/audio-result.json")
    audio = read_master_audio(root / "audio", record["audio"]["receiptHash"], selection)
    if audio["executionInputHash"] != inputs.value["executionInputHash"]:
        raise RuntimeError("opening audio is from a different execution input")
    _read_captions(record, inputs, root)
    return selection, audio


def _unchanged(context: tuple, selected: tuple) -> None:
    """Recheck original dependencies and held receipts after media observation."""
    root, held, inputs, pipeline, record = context
    selection, audio = selected
    observe_inputs(inputs)
    if digest(observe_pipeline(inputs)) != digest(pipeline):
        raise RuntimeError("opening current source/tool closure changed during readback")
    revalidate_master_selection(selection)
    check_held_artifacts(record, audio, root)
    if os.path.lexists(root / "media-failed.json") or os.path.lexists(root / "audio/audio-failed.json"):
        raise RuntimeError("opening attempt failed during readback")
    if digest(_record(root, held)) != digest(record) or file_hash(held.claim_path) != held.claim_sha256:
        raise RuntimeError("opening held result or execution claim changed during readback")
    verify_short_geometry(record["fullProgram"], inputs, root / "full-program-base", selection)
    _read_captions(record, inputs, root)


def read_result(paths: tuple[Path, Path], held: ReadAuthority, timeout: float) -> dict:
    """Prove one actual completion under a remaining, never renewed, work budget."""
    input_path, root = paths
    clock, started = opening_clock(timeout), time.monotonic()
    with use_process_deadline(clock):
        record = clock.phase("held-result", lambda: _record(root, held))
        claim = clock.phase("held-claim", lambda: read_execution_claim(paths,
            (held.input_sha256, held.claim_path, held.claim_sha256)))
        inputs = clock.phase("current-input-and-sources", lambda: _current_inputs(input_path, held.input_sha256, record, clock))
        _identity(record, inputs, claim)
        rows = clock.phase("exact-profile-and-frames", lambda: executable_frames(inputs))
        pipeline = clock.phase("current-code-and-tools", lambda: observe_pipeline(inputs))
        if digest(pipeline) != digest(record["pipeline"]):
            raise RuntimeError("opening result source/tool closure is stale")
        selection, audio = clock.phase("held-whole-master-and-excerpts", lambda: _full_program(record, inputs, root))
        clock.phase("exact-graphic-artifacts", lambda: read_graphics(record, rows, root))
        tools = selection.master.source_bus.admission.tools
        clock.phase("actual-range-media-readback", lambda: _read_picture_ranges(record, audio, inputs, (root, tools, clock)))
        clock.phase("final-source-result-recheck", lambda: _unchanged((root, held, inputs, pipeline, record), (selection, audio)))
        return {"schemaVersion": 1, "kind": "guided-opening-media-readback", "status": "verified",
            "scope": "exact-held-private-media-not-opening-or-delivery-approval", "executionId": inputs.value["executionId"],
            "inputSha256": held.input_sha256, "executionInputHash": inputs.value["executionInputHash"],
            "claimSha256": held.claim_sha256, "receiptPath": str(root / "media-result.json"),
            "receiptSha256": held.receipt_sha256, "receiptHash": held.receipt_hash,
            "elapsedMs": round((time.monotonic() - started) * 1000), "stages": clock.events,
            "processGroupAndDockerCleanup": "requires-separate-owned-server-observation",
            "currentJournalAndLease": "requires-separate-owned-server-observation",
            "openingApproved": False, "deliveryApproved": False}


def _current_inputs(path: Path, sha: str, record: dict, clock: OpeningExecutionClock) -> OpeningInputs:
    """Only new presenter reads need ephemeral same-initial-hash source identities."""
    from headless.external_media_verification import SourceVerificationRuntime

    if is_presenter_profile(record.get("profile")):
        return read_current_inputs(path, sha, SourceVerificationRuntime(clock.remaining))
    return read_current_inputs(path, sha)


def _read_picture_ranges(record: dict, audio: dict, inputs: OpeningInputs, context: tuple) -> None:
    """Keep the existing timed A/V phase and add a held new-class graph read scope."""
    root, tools, clock = context
    if not is_presenter_profile(inputs.value.get("profile")):
        read_ranges(record, audio, (root, inputs.documents["authority"], tools))
        return
    from guided_presenter_capture import PresenterCaptureContext
    from guided_presenter_opening_read import opening_presenter_read_lane

    captions = read_prepared_captions(record["fullProgram"], inputs, root / "full-program-base", clock.remaining)
    runtime = PresenterCaptureContext(tools, str(root), clock, clock.remaining)
    with opening_presenter_read_lane(inputs, record, runtime, captions) as lane:
        read_ranges(record, audio, (root, inputs.documents["authority"], tools), lane)


def _read_captions(record: dict, inputs: OpeningInputs, root: Path) -> None:
    """Read original observations only under the caller's already active deadline."""
    from palmier.process_deadline import process_timeout
    held = read_prepared_captions(record["fullProgram"], inputs, root / "full-program-base", process_timeout)
    assert_opening_caption_layers(record, inputs, held)
    from guided_caption_screen import screen_context
    from guided_caption_screen_read import verify_screen
    verify_screen(record, screen_context(inputs, held, False), process_timeout)


def main() -> int:
    """Emit exactly one closed read-only completion or retain a nonzero failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    for flag in ("input-sha256", "execution-claim", "execution-claim-sha256", "receipt-sha256", "receipt-hash"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    for flag in ("source-color-input", "source-color-input-sha256",
                 "source-color-reservation-archive", "source-color-reservation-archive-sha256"):
        parser.add_argument("--" + flag)
    args = parser.parse_args()
    held = ReadAuthority(args.input_sha256, Path(args.execution_claim), args.execution_claim_sha256,
                         args.receipt_sha256, args.receipt_hash)
    try:
        from guided_source_color_read_transport import parse_source_color_read_transport
        transport = parse_source_color_read_transport((args.source_color_input, args.source_color_input_sha256,
            args.source_color_reservation_archive, args.source_color_reservation_archive_sha256))
        result = _selected_read((args.input, args.output), held, args.timeout_seconds, transport)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "openingApproved": False}), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")), flush=True)
    return 0


def _selected_read(paths: tuple, held: ReadAuthority, timeout: float, transport: object) -> dict:
    """No flags retain the original three-argument reader; explicit quartet selects schema2."""
    if transport is None:
        return read_result(paths, held, timeout)
    from guided_source_color_read import read_source_color_result
    return read_source_color_result(paths, held, timeout, transport)


if __name__ == "__main__":
    raise SystemExit(main())
