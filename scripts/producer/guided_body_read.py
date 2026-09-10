"""Strong readback of one separately held stopped body-worker completion.

Read-only: no plan/media writes, render, repair, selector discovery or approval.
The caller still owes current journal/lease, original work time and independent
process/Docker cleanup. A self-hashed body-result.json cannot select itself.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from audio.program_master_excerpt import _owned_directory
from cut_preview_io import bound_json, digest, file_hash
from guided_body_budget import bind_body_budget
from guided_body_contract import BODY_PROFILE, BODY_SCOPE, BodyInvocation
from guided_body_execution import body_clock
from guided_body_inputs import BodyControl, read_body_control
from guided_body_media import arguments
from guided_body_read_proof import read_body_graphics
from guided_body_read_entry import BodyReadAuthority, BodyReadLifetime
from guided_body_result import observe_body_media, verify_body_media_files
from guided_body_source_color_result import body_source_result_identity, recheck_body_source_result, READBACK_SCOPE
from guided_body_work import (BodyWork, admit_body_templates, prepare_body_work,
                              read_body_preparation, read_body_inputs, replay_body_source_color)
from guided_opening_inputs import closed, hash_value
from palmier.process_deadline import use_process_deadline
from guided_caption_profile import caption_screen_fields


def read_body_record(root: Path, held: BodyReadAuthority) -> dict:
    """Failed, partial or substituted completions remain unselectable."""
    _owned_directory(root)
    if os.path.lexists(root / "body-failed.json"):
        raise RuntimeError("body attempt failed; any orphan result is unselectable")
    value = bound_json(root / "body-result.json", hash_value(held.receipt_sha256))
    body = {key: item for key, item in value.items() if key != "receiptHash"}
    if value.get("receiptHash") != hash_value(held.receipt_hash) or digest(body) != held.receipt_hash:
        raise RuntimeError("body result differs from actual held completion")
    entry = bound_json(root / "body-worker-entry.json")
    expected = {"schemaVersion": 1, "kind": "guided-body-worker-entry",
        "activationPath": str(held.invocation.activation_path),
        "activationSha256": held.invocation.activation_sha256, "inputSha256": held.invocation.input_sha256}
    if digest(entry) != digest(expected):
        raise RuntimeError("body completion has no matching actual worker entry")
    return value


def _identity(record: dict, control: BodyControl) -> None:
    """No body/delivery approval, original authority or exact invocation may drift."""
    invocation = control.invocation
    expected = {**body_source_result_identity(record, control), "kind": "guided-body-media-result", "status": "complete",
        "scope": BODY_SCOPE, "profile": control.value.get("profile", BODY_PROFILE), "executionId": control.value["executionId"],
        "inputPath": str(invocation.input_path), "inputSha256": invocation.input_sha256,
        "executionActivationPath": str(invocation.activation_path),
        "executionActivationSha256": invocation.activation_sha256,
        "references": control.value["references"], "bodyApproved": False, "deliveryApproved": False}
    closed(record, set(expected) | {"pipeline", "workload", "templates", "graphics", "resolvedClips",
        "composition", "programDeliveryReceipt", "media", "stages", "receiptHash"}
        | caption_screen_fields(control.value.get("profile")), "body actual media result")
    if any(type(record[key]) is not type(value) or digest(record[key]) != digest(value)
           for key, value in expected.items()):
        raise RuntimeError("body receipt activation/source/scope differs")
    if type(record["stages"]) is not list or not 1 <= len(record["stages"]) <= 2048 \
            or any(type(row) is not dict or row.get("status") != "complete" for row in record["stages"]):
        raise RuntimeError("body receipt lacks bounded completed work stages")


def _graphics(record: dict, work: BodyWork) -> None:
    """Recheck all-row profile/template/workload and actual full graph proof refs."""
    admit_body_templates(work)
    if digest(record["workload"]) != digest(work.workload) or digest(record["templates"]) != digest(work.templates):
        raise RuntimeError("body all-row template/workload differs from held execution")
    read_body_graphics(record, work)
    _screen(record, work)


def _media(record: dict, work: BodyWork) -> None:
    """Whole final decode, exact full master/AAC, retained picture and whole QC."""
    actual = observe_body_media(work.control.root, work.inputs, work.selection,
        {"composition": record["composition"], "programDeliveryReceipt": record["programDeliveryReceipt"], "captions": work.captions})
    if digest(actual) != digest(record["media"]):
        raise RuntimeError("body actual complete media/QC differs from held completion")


def _unchanged(work: BodyWork, record: dict, held: BodyReadAuthority) -> None:
    """Final exact byte/clock guard prevents a raced read from selecting new output."""
    work.revalidate()
    recheck_body_source_result(record, work)
    read_body_graphics(record, work)
    _screen(record, work)
    verify_body_media_files(work.control.root, record["media"])
    if digest(read_body_record(work.control.root, held)) != digest(record):
        raise RuntimeError("body held completion changed during readback")
    work.guard()


def _screen(record: dict, work: BodyWork) -> None:
    """Reconstruct original full-clock screening beneath actual owner authority."""
    from guided_caption_screen import screen_context
    from guided_caption_screen_read import verify_screen
    verify_screen(record, screen_context(work.inputs, work.captions, True), work.guard)


def _read_control(lifetime: BodyReadLifetime, clock: object) -> BodyControl:
    """Retain original current output metadata before reading any body/source controls."""
    lifetime.check()
    control = read_body_control(lifetime.held.invocation, lifetime.root)
    lifetime.check()
    return control


def read_result(root: Path, held: BodyReadAuthority, timeout: float) -> dict:
    """No publication; one decreasing body remainder across all actual observations."""
    lifetime = BodyReadLifetime(root, held)
    clock = body_clock(timeout)
    lifetime.start_clock(clock)
    started = clock.end - timeout
    lifetime.capture(clock)
    with use_process_deadline(clock):
        control = clock.phase("body-read-control", lambda: _read_control(lifetime, clock))
        bind_body_budget(control, clock)
        lifetime.bind()
        read = clock.phase("body-read-current-inputs", lambda: read_body_inputs(control, clock))
        lifetime.check()
        record = clock.phase("body-read-held-result", lambda: read_body_record(root, held))
        lifetime.check()
        _identity(record, control)
        work = clock.phase("body-read-current-pipeline", lambda: prepare_body_work(control, read.inputs, clock, read.source_color_entry))
        lifetime.check()
        if digest(work.pipeline) != digest(record["pipeline"]):
            raise RuntimeError("body invoked source/tool closure is stale")
        replay_body_source_color(work)
        lifetime.check()
        recheck_body_source_result(record, work)
        clock.phase("body-read-whole-base-master", lambda: read_body_preparation(work))
        clock.phase("body-read-all-graphics", lambda: _graphics(record, work))
        clock.phase("body-read-final-media-and-qc", lambda: _media(record, work))
        clock.phase("body-read-final-revalidation", lambda: _unchanged(work, record, held))
        work.guard()
        fields = recheck_body_source_result(record, work)
        lifetime.check()
        result = {**fields, "kind": "guided-body-media-readback", "status": "verified",
            "scope": READBACK_SCOPE if fields["schemaVersion"] == 2 else "exact-held-private-body-media-not-body-or-delivery-approval",
            "executionId": control.value["executionId"], "inputSha256": held.invocation.input_sha256,
            "executionActivationSha256": held.invocation.activation_sha256,
            "receiptPath": str(root / "body-result.json"), "receiptSha256": held.receipt_sha256,
            "receiptHash": held.receipt_hash, "elapsedMs": round((time.monotonic() - started) * 1000), "stages": clock.events,
            "processGroupAndDockerCleanup": "requires-separate-owned-controller-observation",
            "currentJournalAndLease": "requires-separate-owned-controller-observation",
            "bodyApproved": False, "deliveryApproved": False}
        BodyWork.guard(work)
        lifetime.check()
        return result


def main() -> int:
    """One closed readback DTO; inherited decoder progress cannot corrupt stdout."""
    args = arguments(__doc__, receipt=True)
    invocation = BodyInvocation(args.input, args.input_sha256,
        Path(args.execution_activation), args.execution_activation_sha256)
    held = BodyReadAuthority(invocation, args.receipt_sha256, args.receipt_hash)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = read_result(args.output, held, args.timeout_seconds)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "bodyApproved": False}), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
