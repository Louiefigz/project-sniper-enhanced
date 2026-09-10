"""Private executable opening development class, never a delivery/approval route.

Only an owned server invocation may supply the separately held input-file SHA.
This command cannot authenticate a user-edited authority document or acquire a
project lease. The server must verify its durable decision/current journal and
original generation deadline before/after the actual owned process completes.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path

from audio.program_master_excerpt import ExcerptRanges, _directory, extract_master_audio, read_master_audio
from audio.program_master_selection import revalidate_master_selection
from cut_preview_io import digest, file_hash, write_new
from guided_opening_execution import OpeningExecutionClock, opening_clock
from guided_opening_claim import HeldOpeningClaim, read_execution_claim
from guided_opening_frames import executable_frames
from guided_opening_graphics import graphics_runtime, render_opening_graphics
from guided_opening_graphic_proof import verify_graphics_unchanged
from headless.render_runtime import current_render_build_manifest
from headless.external_media_verification import SourceVerificationRuntime
from guided_opening_inputs import OpeningInputs, PROFILE, observe_inputs, read_current_inputs
from guided_opening_mux import mux_ranges
from guided_opening_picture import compose_ranges
from guided_opening_pipeline import observe_pipeline
from guided_opening_prepare import OpeningPreparation, prepare_full_program
from palmier.process_deadline import use_process_deadline, process_timeout
from guided_short_geometry import verify_short_geometry
from guided_caption_projection import read_caption_projection
from guided_caption_screen import screen_context, screen_intent_preflight, screen_result, require_screen
from guided_presenter_base import require_unowned_presenter_absent
from guided_source_color_media import (
    SourceColorMediaInvocation, parse_source_color_media_invocation,
    prepare_source_color_media, validate_source_color_media_invocation,
)
from guided_source_color_media_evidence import (
    verify_source_color_media_evidence, write_source_color_media_evidence,
)
from guided_source_color_base_context import SourceColorBaseContext
from guided_body_execution import _identity as file_identity, _directory_states
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata

SCOPE = "private-opening-media-not-opening-body-or-delivery-approval"


def _span(value: dict) -> tuple[int, int]:
    """Use the already validated exact absolute frame pair, without new rounding."""
    return value["startFrame"], value["endFrameExclusive"]


def _unchanged(context: tuple, outputs: tuple) -> None:
    """Revalidate whole sources/code/master and exact measured private outputs."""
    inputs, pipeline, prepared, claim = context
    audio, media, graphics = outputs
    if file_hash(claim.path) != claim.sha256:
        raise RuntimeError("opening held execution claim changed")
    observe_inputs(inputs)
    if digest(observe_pipeline(inputs)) != digest(pipeline):
        raise RuntimeError("opening pipeline/tools changed during actual execution")
    revalidate_master_selection(prepared.selection)
    read_master_audio(Path(audio["core"]["path"]).parent, audio["receiptHash"], prepared.selection)
    verify_graphics_unchanged(graphics["evidence"])
    for row in media.values():
        if file_hash(Path(row["path"])) != row["sha256"]:
            raise RuntimeError("opening encoded media changed after qualification")
    verify_short_geometry(prepared.evidence, inputs, prepared.base.parent, prepared.selection)
    if prepared.captions is not None:
        read_caption_projection(prepared.captions, prepared.captions.binding, process_timeout)
    from guided_caption_screen_read import verify_screen
    verify_screen({"graphics": graphics["evidence"], **({"captionLayoutScreen": graphics["captionLayoutScreen"]}
        if "captionLayoutScreen" in graphics else {})}, screen_context(inputs, prepared.captions, False),
        process_timeout)


def _audio(prepared: OpeningPreparation, inputs: OpeningInputs, root: Path, clock: OpeningExecutionClock) -> dict:
    """Extract actual selected full-master ranges, never independently master them."""
    directory = root / "audio"
    directory.mkdir(mode=0o700)
    authority = inputs.documents["authority"]
    ranges = ExcerptRanges(_span(authority["core"]), _span(authority["review"]), inputs.value["executionInputHash"])
    return extract_master_audio(prepared.selection, ranges, directory, clock.remaining)


def _receipt(context: tuple, outputs: tuple, clock: OpeningExecutionClock,
             source_color: dict | None = None) -> dict:
    """Persist actual privately measured facts, with all outstanding review explicit."""
    inputs, pipeline, prepared, claim, root = context
    audio, graphics, pictures, media = outputs
    audio_path = root / "audio/audio-result.json"
    body = {"schemaVersion": 1, "kind": "guided-opening-media-result", "scope": SCOPE,
        "status": "complete", "profile": inputs.value.get("profile", PROFILE), "executionId": inputs.value["executionId"],
        "inputPath": str(inputs.path), "inputSha256": inputs.sha256, "executionInputHash": inputs.value["executionInputHash"],
        "executionClaim": {"path": str(claim.path), "sha256": claim.sha256},
        "authority": inputs.documents["authority"], "documents": inputs.value["documents"], "pipeline": pipeline,
        "fullProgram": prepared.evidence,
        "audio": {"path": str(audio_path), "sha256": file_hash(audio_path), "receiptHash": audio["receiptHash"]},
        "graphics": graphics["evidence"], "pictures": pictures, "media": media, "stages": list(clock.events),
        "openingApproved": False, "deliveryApproved": False, "bodyGraphicsPrepared": False,
        "creativeVisualReview": "not-run", "subjectiveListening": "not-run",
        "qualificationScope": "private-mechanical-frame-audio-and-runtime-evidence-only",
        "processGroupCleanup": "requires-owned-server-observation"}
    if "captionLayoutScreen" in graphics:
        body["captionLayoutScreen"] = graphics["captionLayoutScreen"]
    if source_color is not None:
        body.update(schemaVersion=2, sourceColorEvidence=source_color)
    result = {**body, "receiptHash": digest(body)}
    write_new(root / "media-result.json", result)
    return result


def _execute(inputs: OpeningInputs, root: Path, clock: OpeningExecutionClock, claim: HeldOpeningClaim) -> dict:
    """Execute real ordinary base, full master, original graphics, range and A/V."""
    return _execute_selected(inputs, root, clock, (claim, None))


def _execute_selected(inputs: OpeningInputs, root: Path, clock: OpeningExecutionClock, execution: tuple) -> dict:
    """Keep the legacy route intact; source-color transport uses a distinct actual base owner."""
    claim, invocation = execution
    validate_source_color_media_invocation(invocation)
    require_unowned_presenter_absent(inputs.documents["candidatePlan"])
    rows = clock.phase("exact-profile-and-frames", lambda: executable_frames(inputs))
    screen_intent_preflight(inputs, rows)
    pipeline = clock.phase("pinned-code-and-tools", lambda: observe_pipeline(inputs))
    if rows:
        clock.phase("sealed-renderer-admission", lambda: current_render_build_manifest(graphics_runtime(inputs, pipeline, claim)))
    if invocation is None:
        prepared = clock.phase("ordinary-full-program-preparation", lambda: prepare_full_program(inputs, root, clock.remaining))
        source_context = None
    else:
        prepared, source_context = prepare_source_color_media(inputs, claim, (root, clock, pipeline), invocation)
    return _finish_execution(inputs, root, clock, (claim, pipeline, rows, prepared, source_context))


def _finish_execution(inputs: OpeningInputs, root: Path, clock: OpeningExecutionClock, execution: tuple) -> dict:
    """Share the existing complete audio/graphics/range checks, without schema1 fallback."""
    claim, pipeline, rows, prepared, source_context = execution
    audio = clock.phase("exact-full-master-excerpts", lambda: _audio(prepared, inputs, root, clock))
    screening = screen_context(inputs, prepared.captions, False)
    context = root, pipeline, clock, claim
    graphics = render_opening_graphics(inputs, rows, context, screening) if screening is not None \
        else render_opening_graphics(inputs, rows, context)
    if screening is not None:
        screened = clock.phase("caption-graphic-layout-screen", lambda: screen_result(screening, graphics["evidence"], clock.remaining))
        require_screen(screened)
        graphics["captionLayoutScreen"] = screened
    tools = prepared.selection.master.source_bus.admission.tools
    pictures = clock.phase("ordinary-exact-range-composition", lambda: compose_ranges(prepared.base,
        graphics["clips"], (root, inputs.documents["authority"], tools), prepared.captions))
    media = clock.phase("exact-picture-copy-and-aac", lambda: mux_ranges(root, pictures, audio, tools))
    context = inputs, pipeline, prepared, claim
    outputs = audio, media, graphics
    clock.phase("whole-input-and-result-revalidation", lambda: _unchanged(context, outputs))
    source_color = None if source_context is None else clock.phase("source-color-evidence-publication",
        lambda: write_source_color_media_evidence(source_context, prepared, root))
    receipt_arguments = (*context, root), (audio, graphics, pictures, media), clock
    result = _receipt(*receipt_arguments) if source_color is None else _receipt(*receipt_arguments, source_color)
    clock.phase("post-receipt-held-byte-check", lambda: _unchanged(context, outputs))
    if source_context is not None:
        clock.phase("source-color-post-receipt-check", lambda: verify_source_color_media_evidence(source_context, source_color))
    print(json.dumps({"kind": "guided-opening-final-revalidation-timing",
        "scope": "private-work-timing-not-approval", "stage": clock.events[-1]}), file=sys.stderr)
    return _completion(inputs, root, clock, (claim, result, source_context, source_color))


def _completion(inputs: OpeningInputs, root: Path, clock: OpeningExecutionClock, execution: tuple) -> dict:
    """Bind original result bytes BEFORE final callbacks; close bytes, metadata and deadline last."""
    claim, result, source_context, source_color = execution
    location = root / "media-result.json"
    parents = tuple(location.parents)
    ancestors, identity = _directory_states(parents), file_identity(location.lstat())
    sha256 = file_hash(location)
    clock.remaining()
    _same_completion_file(location, (parents, ancestors, identity))
    completion = {"schemaVersion": 1 if source_color is None else 2, "kind": "guided-opening-media-completion", "status": "complete",
        "executionId": inputs.value["executionId"], "inputSha256": inputs.sha256,
        "executionInputHash": inputs.value["executionInputHash"],
        "executionClaimSha256": claim.sha256,
        "receiptPath": str(location), "receiptSha256": sha256,
        "receiptHash": result["receiptHash"], "openingApproved": False, "deliveryApproved": False,
        **({"sourceColorEvidence": source_color} if source_color is not None else {})}
    original = hold_read_metadata(completion)
    if source_context is not None:
        SourceColorBaseContext.assert_current(source_context)
    _same_completion_file(location, (parents, ancestors, identity))
    if not same_read_metadata(completion, original):
        raise RuntimeError("opening completion metadata changed during original callback")
    clock.remaining()
    return completion


def _same_completion_file(location: Path, original: tuple) -> None:
    """Check original ancestry and regular-file identity without another byte hash or callback."""
    parents, ancestors, identity = original
    if _directory_states(parents) != ancestors or file_identity(location.lstat()) != identity \
            or _directory_states(parents) != ancestors:
        raise RuntimeError("opening completion receipt bytes or ancestry changed during original callback")


def run(input_path: Path, root: Path, authority: tuple[str, float, Path, str],
        source_color: SourceColorMediaInvocation | None = None) -> dict:
    """No-replace private run; failed or postdeadline results are not selectable."""
    expected_sha, timeout, claim_path, claim_sha = authority
    validate_source_color_media_invocation(source_color)
    clock, started = opening_clock(timeout), time.monotonic()
    _directory(root)
    try:
        with use_process_deadline(clock):
            return _run_owned(input_path, root, clock, (authority, source_color))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = {"schemaVersion": 1, "kind": "guided-opening-media-failed", "scope": SCOPE, "status": "failed",
            "inputSha256": expected_sha, "error": str(error), "stages": clock.events,
            "elapsedMs": round((time.monotonic() - started) * 1000), "openingApproved": False,
            "deliveryApproved": False, "processGroupCleanup": "requires-owned-server-observation"}
        try:
            write_new(root / "media-failed.json", failure)
        except (OSError, RuntimeError) as persistence_error:
            error.add_note(f"Could not retain private media failure: {persistence_error}")
        raise


def _run_owned(input_path: Path, root: Path, clock: OpeningExecutionClock, invocation: tuple) -> dict:
    """Keep original source admission inside the original process deadline, with explicit routing."""
    authority, source_color = invocation
    expected_sha, _timeout, claim_path, claim_sha = authority
    claim = clock.phase("held-execution-claim", lambda: read_execution_claim((input_path, root),
        (expected_sha, claim_path, claim_sha)))
    write_new(root / "worker-entry.json", {"schemaVersion": 1, "kind": "guided-opening-worker-entry",
        "claimPath": str(claim.path), "claimSha256": claim.sha256, "inputSha256": expected_sha})
    inputs = clock.phase("exact-input-and-source-admission", lambda: read_current_inputs(
        input_path, expected_sha, SourceVerificationRuntime(clock.remaining)))
    if source_color is None:
        return _execute(inputs, root, clock, claim)
    return _execute_selected(inputs, root, clock, (claim, source_color))


def main() -> int:
    """Return held completion bytes only after the actual private media work."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--execution-claim", type=Path, required=True)
    parser.add_argument("--execution-claim-sha256", required=True)
    for flag in ("source-color-input", "source-color-input-sha256", "source-color-producer-dir", "source-color-resource-dir"):
        parser.add_argument("--" + flag)
    args = parser.parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            source_color = parse_source_color_media_invocation((args.source_color_input, args.source_color_input_sha256,
                args.source_color_producer_dir, args.source_color_resource_dir))
            invocation = args.input, args.output, (args.input_sha256, args.timeout_seconds,
                                                  args.execution_claim, args.execution_claim_sha256)
            result = run(*invocation) if source_color is None else run(*invocation, source_color)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "openingApproved": False}), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
