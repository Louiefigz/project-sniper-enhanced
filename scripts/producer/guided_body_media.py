"""Foreground owned full-body mechanical candidate, never approval or delivery.

The controller holds exact activation, original approval/journal and one work
remainder. Ordinary source-float assembly, full Audit B and prefix oracle remain
mandatory. Interruption does not permit resuming or selecting orphan outputs.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

from assemble import AssembleJob, assemble
from audio.program_master_excerpt import _directory
from cut_preview_io import digest, file_hash, write_new
from guided_body_budget import bind_body_budget
from guided_body_contract import BODY_PROFILE, BODY_SCOPE, BodyInvocation
from guided_body_execution import body_clock
from guided_body_graphics import BodyGraphicsContext, BodyGraphicsOwner
from guided_body_inputs import read_body_control
from guided_body_result import observe_body_media, verify_body_media_files
from guided_body_source_color_result import body_source_result_fields, recheck_body_source_result
from guided_body_work import (BodyWork, admit_body_templates, prepare_body_work,
                              read_body_preparation, read_body_inputs, replay_body_source_color)
from guided_opening_graphic_proof import verify_graphics_unchanged
from palmier.process_deadline import use_process_deadline
from guided_caption_execution import OwnedCaptionExecution
from guided_caption_screen import screen_context, screen_intent_preflight, admit_screen
from guided_presenter_base import require_unowned_presenter_absent


def _job(work: BodyWork, owner: BodyGraphicsOwner) -> AssembleJob:
    """Use original exact preparation paths in one NEW private candidate directory."""
    root = work.control.root / "body-candidate"
    root.mkdir(mode=0o700)
    _directory(root)
    record = work.control.documents["openingResult"]
    base = record["fullProgram"]["base"]["path"]
    refs, authority = work.inputs.value["documents"], work.inputs.documents["authority"]
    return AssembleJob(base=base, plan=copy.deepcopy(work.inputs.documents["candidatePlan"]),
        out=str(root / "final.mp4"), cache_dir=None,
        fingerprint_path=str(Path(base).parent / "base.fingerprint.json"),
        manifest=refs["manifest"]["path"], audio_clock_policy="source-float-v2",
        plan_path=refs["candidatePlan"]["path"],
        held_program_selection=(record["fullProgram"]["fullMasterSelectionEventPath"],
                                record["fullProgram"]["fullMasterSelectionEventSha256"]),
        graphic_frame_clock=(authority["frameRate"], authority["totalFrames"]), owned_graphics=owner.hooks())


def _assemble(work: BodyWork, owner: BodyGraphicsOwner) -> dict:
    """Time legacy assembly without nesting alarms over owned protected cleanup.

    The enclosing controller's original process deadline is the final backstop
    for direct legacy subprocesses; this is NOT a claim all have local timers.
    Hooks and publication guards still check this same decreasing work budget.
    """
    event = {"stage": "body-ordinary-whole-assembly-and-Audit-B", "status": "failed",
             "timingScope": "timing-only-original-controller-group-backstop"}
    started = time.monotonic()
    try:
        work.guard()
        result = assemble(_job(work, owner))
        work.guard()
        if owner.composition is None or owner.resolved_clips is None \
                or digest(result.get("ownedCompositionEvidence")) != digest(owner.composition):
            raise RuntimeError("body assembler omitted its actual owned full graph evidence")
        event["status"] = "complete"
        return result
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        event["error"] = str(error)
        raise
    finally:
        event["elapsedMs"] = round((time.monotonic() - started) * 1000)
        work.clock.events.append(event)


def _unchanged(work: BodyWork, owner: BodyGraphicsOwner, media: dict) -> None:
    """No changed source, graph, output or failed attempt can publish completion."""
    work.revalidate()
    verify_graphics_unchanged(owner.evidence)
    verify_body_media_files(work.control.root, media)
    from guided_caption_screen_read import verify_screen
    verify_screen({"graphics": owner.evidence, **({"captionLayoutScreen": owner.caption_screen}
        if owner.caption_screen is not None else {})}, owner.screening, work.guard)
    work.guard()


def _receipt(work: BodyWork, owner: BodyGraphicsOwner, outputs: tuple[dict, dict]) -> dict:
    """Retain immutable actual observations, never a self-authorizing result flag."""
    summary, media = outputs
    control, invocation = work.control, work.control.invocation
    body = {**body_source_result_fields(work), "kind": "guided-body-media-result", "status": "complete",
        "scope": BODY_SCOPE, "profile": control.value.get("profile", BODY_PROFILE), "executionId": control.value["executionId"],
        "inputPath": str(invocation.input_path), "inputSha256": invocation.input_sha256,
        "executionActivationPath": str(invocation.activation_path),
        "executionActivationSha256": invocation.activation_sha256, "references": control.value["references"],
        "pipeline": work.pipeline, "workload": work.workload, "templates": work.templates,
        "graphics": owner.evidence, "resolvedClips": list(owner.resolved_clips),
        "composition": owner.composition, "programDeliveryReceipt": summary["programDeliveryReceipt"],
        "media": media, "stages": list(work.clock.events), "bodyApproved": False, "deliveryApproved": False}
    if owner.caption_screen is not None:
        body["captionLayoutScreen"] = owner.caption_screen
    result = {**body, "receiptHash": digest(body)}
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 16 * 1024 * 1024:
        raise RuntimeError("body actual evidence exceeds the bounded16MiB result class")
    work.guard()
    write_new(control.root / "body-result.json", result)
    work.guard()
    return result


def _execute(work: BodyWork) -> dict:
    """Only after all-row admission, use the actual ordinary renderer and assembler."""
    require_unowned_presenter_absent(work.inputs.documents["candidatePlan"])
    clock, root = work.clock, work.control.root
    rows = clock.phase("body-all-row-workload-and-templates", lambda: admit_body_templates(work))
    screen_intent_preflight(work.inputs, rows)
    clock.phase("body-original-whole-base-master", lambda: read_body_preparation(work))
    (root / "graphics").mkdir(mode=0o700)
    (root / "graphics/attempts").mkdir(mode=0o700)
    owner = BodyGraphicsOwner(BodyGraphicsContext(work.control, work.inputs,
        work.pipeline["opening"], clock, work.guard), rows)
    if work.captions is not None:
        owner.captions = OwnedCaptionExecution(work.captions, work.guard)
    owner.screening = screen_context(work.inputs, work.captions, True)
    if owner.screening is not None:
        owner.observed_orders = clock.phase("body-caption-layout-admission", lambda: admit_screen(owner.screening, work.guard))
    summary = _assemble(work, owner)
    media = clock.phase("body-complete-final-media-and-QC-read", lambda: observe_body_media(root,
        work.inputs, work.selection, {"composition": owner.composition,
                                     "programDeliveryReceipt": summary["programDeliveryReceipt"], "captions": work.captions}))
    clock.phase("body-whole-input-and-result-revalidation", lambda: _unchanged(work, owner, media))
    record = _receipt(work, owner, (summary, media))
    clock.phase("body-post-receipt-revalidation", lambda: _unchanged(work, owner, media))
    receipt = root / "body-result.json"
    sha = file_hash(receipt)
    work.guard()
    return {**recheck_body_source_result(record, work), "kind": "guided-body-media-completion", "status": "complete",
        "executionId": work.control.value["executionId"], "inputSha256": work.control.invocation.input_sha256,
        "executionActivationSha256": work.control.invocation.activation_sha256,
        "receiptPath": str(receipt), "receiptSha256": sha, "receiptHash": record["receiptHash"],
        "bodyApproved": False, "deliveryApproved": False}


def run(invocation: BodyInvocation, root: Path, timeout: float) -> dict:
    """A new-only worker entry; a late/orphan receipt stays unselectable on failure."""
    clock, started = body_clock(timeout), time.monotonic()
    _directory(root)
    try:
        with use_process_deadline(clock):
            control = clock.phase("body-held-activation-and-input", lambda: read_body_control(invocation, root))
            bind_body_budget(control, clock)
            write_new(root / "body-worker-entry.json", {"schemaVersion": 1, "kind": "guided-body-worker-entry",
                "activationPath": str(invocation.activation_path), "activationSha256": invocation.activation_sha256,
                "inputSha256": invocation.input_sha256})
            read = clock.phase("body-original-current-source-inputs", lambda: read_body_inputs(control, clock))
            work = clock.phase("body-current-pipeline-and-claim", lambda: prepare_body_work(control, read.inputs, clock, read.source_color_entry))
            replay_body_source_color(work)
            return _execute(work)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = {"schemaVersion": 1, "kind": "guided-body-media-failed", "scope": BODY_SCOPE, "status": "failed",
            "inputSha256": invocation.input_sha256, "error": str(error), "stages": clock.events,
            "elapsedMs": round((time.monotonic() - started) * 1000), "bodyApproved": False,
            "deliveryApproved": False, "processGroupCleanup": "requires-owned-controller-observation"}
        try:
            write_new(root / "body-failed.json", failure)
        except (OSError, RuntimeError) as persistence_error:
            error.add_note(f"Could not retain private body failure: {persistence_error}")
        raise


def arguments(description: str, receipt: bool = False) -> argparse.Namespace:
    """Fixed internal body CLI vocabulary, with no runtime or arbitrary store switch."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    for flag in ("input-sha256", "execution-activation", "execution-activation-sha256"):
        parser.add_argument("--" + flag, required=True)
    if receipt:
        for flag in ("receipt-sha256", "receipt-hash"):
            parser.add_argument("--" + flag, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    return parser.parse_args()


def main() -> int:
    """One bounded completion only; all normal assembler progress stays on stderr."""
    args = arguments(__doc__)
    invocation = BodyInvocation(args.input, args.input_sha256,
        Path(args.execution_activation), args.execution_activation_sha256)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = run(invocation, args.output, args.timeout_seconds)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "bodyApproved": False}), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
