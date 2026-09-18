"""Separate schema2 cold media readback under the original caller's remainder.

No public activation or cleanup authority is granted here. Callers must supply
the actual stopped-process sidecar and authenticated final-cleanup archive,
in addition to the existing independently held result/claim hashes. All usual
whole-master, graphic and native range checks remain required. Identity BT709
observations are not a gamut measurement, grade or perceptual qualification.
"""
from __future__ import annotations

import time
from copy import deepcopy
from collections.abc import Callable
from functools import partial
from pathlib import Path

from guided_opening_claim import read_execution_claim_metadata
from guided_opening_execution import OpeningExecutionClock, opening_clock
from guided_opening_frames import executable_frames
from guided_opening_inputs import read_current_inputs
from guided_opening_read import ReadAuthority, _record, _identity, _full_program, _read_picture_ranges, _unchanged
from guided_opening_result import read_graphics
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_read_scope import SourceColorReadScope
from guided_source_color_read_transport import SourceColorReadTransport, validate_source_color_read_transport
from guided_source_color_read_entry import capture_source_color_read_entry, assert_source_color_read_entry
from headless.external_media_verification import SourceVerificationRuntime
from palmier.process_deadline import use_process_deadline

STAGES = ("held-result", "held-claim", "current-input-and-sources", "exact-profile-and-frames", "current-code-and-tools",
          "source-color-original-observation-replay", "held-whole-master-and-excerpts", "source-color-base-consumption-readback",
          "exact-graphic-artifacts", "actual-range-media-readback", "final-source-result-recheck")


def _original(paths: tuple, held: ReadAuthority, transport: SourceColorReadTransport) -> tuple:
    """Retain exact invocation data before creating even the local remaining clock."""
    validate_source_color_read_transport(transport)
    if transport is None or type(held) is not ReadAuthority or type(paths) is not tuple or len(paths) != 2 \
            or any(type(path) is not type(Path()) for path in paths):
        raise ValueError("source-color read requires explicit original paths, receipt and final references")
    return (tuple((id(path), str(path)) for path in paths), id(held), held.input_sha256, str(held.claim_path),
            held.claim_sha256, held.receipt_sha256, held.receipt_hash, id(transport))


def _check_original(arguments: tuple, original: object) -> None:
    """Never adopt changed authority or optional transport after a read callback."""
    if not same_read_metadata(_original(*arguments), original):
        raise RuntimeError("source-color read original invocation changed")


def _entry_current(context: tuple, clock: OpeningExecutionClock) -> None:
    """Refuse changed original authority BEFORE a later file/source admission can use it."""
    arguments, original, entry = context
    _check_original(arguments, original)
    assert_source_color_read_entry(entry, clock)
    _check_original(arguments, original)


def _phase(clock: OpeningExecutionClock, context: tuple, name: str, operation: Callable[[], object]) -> object:
    """Keep every stage on the same clock and original entry, including failed early callbacks."""
    _entry_current(context, clock)
    count, previous = len(clock.events), hold_read_metadata(clock.events)
    if count >= len(STAGES) or name != STAGES[count]:
        raise RuntimeError("source-color read phase order differs")
    value = OpeningExecutionClock.phase(clock, name, operation)
    _entry_current(context, clock)
    if len(clock.events) != count + 1 or not same_read_metadata(clock.events[:count], previous):
        raise RuntimeError("source-color read original phase history changed")
    return value


def _timing(result: dict, clock: OpeningExecutionClock) -> None:
    """Require all eleven actual successful phases and honest independently rounded totals."""
    rows, elapsed = result["stages"], result["elapsedMs"]
    if type(rows) is not list or len(rows) != len(STAGES) or type(elapsed) is not int or not 0 <= elapsed <= 1_500_000 \
            or not same_read_metadata(rows, hold_read_metadata(clock.events)):
        raise RuntimeError("source-color readback timing lacks actual complete phase coverage")
    total = 0
    for row, name in zip(rows, STAGES):
        if type(row) is not dict or set(row) != {"stage", "status", "elapsedMs"} \
                or row["stage"] != name or row["status"] != "complete" \
                or type(row["elapsedMs"]) is not int or not 0 <= row["elapsedMs"] <= elapsed:
            raise RuntimeError("source-color readback phase is failed, reordered or unbounded")
        total += row["elapsedMs"]
    if total > elapsed + (len(STAGES) + 1) // 2:
        raise RuntimeError("source-color readback phase sum exceeds actual elapsed time")


def _verify(context: tuple, selected: tuple, scope: SourceColorReadScope) -> None:
    """Keep all original legacy whole-output checks, then close every source-color hold."""
    _unchanged(context, selected)
    SourceColorReadScope.final_check(scope)


def _result(held: ReadAuthority, scope: SourceColorReadScope, started: float) -> dict:
    """Report only complete exact read coverage; retain false quality/approval claims."""
    inputs, root, clock = scope.inputs, scope.controls[0], scope.controls[2]
    return {"schemaVersion": 2, "kind": "guided-opening-media-readback", "status": "verified",
        "scope": "exact-source-color-held-private-media-not-opening-or-delivery-approval",
        "executionId": inputs.value["executionId"], "inputSha256": held.input_sha256,
        "executionInputHash": inputs.value["executionInputHash"], "claimSha256": held.claim_sha256,
        "receiptPath": str(root / "media-result.json"), "receiptSha256": held.receipt_sha256,
        "receiptHash": held.receipt_hash, "sourceColorEvidence": deepcopy(scope.record["sourceColorEvidence"]),
        "sourceColorRecordsReplayed": True, "basePictureConsumptionVerified": True,
        "gamutMeasured": False, "gradeApplied": False, "colorQualified": False,
        "elapsedMs": round((time.monotonic() - started) * 1000), "stages": deepcopy(clock.events),
        "processGroupAndDockerCleanup": "requires-separate-owned-server-observation",
        "currentJournalAndLease": "requires-separate-owned-server-observation",
        "openingApproved": False, "deliveryApproved": False}


def _read(paths: tuple[Path, Path], held: ReadAuthority, execution: tuple, transport: SourceColorReadTransport) -> dict:
    """Execute the closed eleven-stage source-color readback without a second clock."""
    clock, started, original, entry = execution
    input_path, root = paths
    arguments = paths, held, transport
    phase = partial(_phase, clock, (arguments, original, entry))
    record = phase("held-result", lambda: _record(root, held))
    if type(record.get("schemaVersion")) is not int or record["schemaVersion"] != 2:
        raise RuntimeError("explicit source-color read requires its original schema2 result")
    claim = phase("held-claim", lambda: read_execution_claim_metadata(paths,
        (held.input_sha256, held.claim_path, held.claim_sha256)))
    inputs = phase("current-input-and-sources", lambda: read_current_inputs(
        input_path, held.input_sha256, SourceVerificationRuntime(clock.remaining)))
    _identity(record, inputs, claim, True)
    rows = phase("exact-profile-and-frames", lambda: executable_frames(inputs))
    scope = phase("current-code-and-tools", lambda: SourceColorReadScope(inputs, record, (root, claim, clock, held, entry), transport))
    phase("source-color-original-observation-replay", lambda: SourceColorReadScope.replay_observations(scope))
    selection, audio = phase("held-whole-master-and-excerpts", lambda: _full_program(record, inputs, root))
    phase("source-color-base-consumption-readback", lambda: SourceColorReadScope.replay_consumption(scope))
    phase("exact-graphic-artifacts", lambda: read_graphics(record, rows, root))
    tools = selection.master.source_bus.admission.tools
    phase("actual-range-media-readback", lambda: _read_picture_ranges(record, audio, inputs, (root, tools, clock)))
    phase("final-source-result-recheck", lambda: _verify((root, held, inputs, scope.pipeline, record), (selection, audio), scope))
    _check_original(arguments, original)
    result = _result(held, scope, started)
    fixed = hold_read_metadata(result)
    SourceColorReadScope.final_check(scope)
    _check_original(arguments, original)
    if not same_read_metadata(result, fixed):
        raise RuntimeError("source-color final readback data changed during its last callback")
    result["elapsedMs"] = round((time.monotonic() - started) * 1000)
    _timing(result, clock)
    OpeningExecutionClock.remaining(clock)
    return result


def read_source_color_result(paths: tuple[Path, Path], held: ReadAuthority, timeout: float,
                             transport: SourceColorReadTransport) -> dict:
    """Require explicit new transport; legacy/schema2 results cannot silently interchange."""
    original = hold_read_metadata(_original(paths, held, transport))
    started = time.monotonic()
    clock = opening_clock(timeout)
    entry = capture_source_color_read_entry(paths, held, transport, clock)
    _entry_current(((paths, held, transport), original, entry), clock)
    with use_process_deadline(clock):
        return _read(paths, held, (clock, started, original, entry), transport)
