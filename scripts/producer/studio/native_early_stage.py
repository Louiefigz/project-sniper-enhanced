"""Cheap package checks and whole-program audio before any Short capture or picture owner.

The export pipeline calls ``run_early_checks`` first: static preflight fails a
blocked package in seconds, then the bound audio stage is prepared under its own
supervised owner (or an already sealed compatible stage is re-verified). The
in-render static gate reuses the early result only while its exact source,
validator and reference state still match; otherwise it reruns.
"""
from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from cut_preview_io import bound_json, write_new
from stage_timing import stage_span
from studio.native_audio_seal import FAILED_NAME, SEAL_NAME, read_sealed_stage
from studio.native_audio_stage import AudioStageFailure, AudioStagePlan, prepare_stage
from studio.native_preflight import preflight, read_completed, validator_state
from studio.native_preflight_inputs import source_state
from studio.native_reference_reuse import reference_snapshot
from studio.native_runtime import digest

STATIC_DIRECTORY = 'static'
STATIC_FILES = ('inputs.json', 'result.json', 'completion.json')
SEAL_FILES = ('request', 'owner', 'result', 'masterReceipt')
# Stage limits; inside a budgeted export the owner is further clamped to the launch allocation.
AUDIO_STAGE_WORK_SECONDS = 300.0
AUDIO_STAGE_CAPACITY_WAIT_SECONDS = 600.0


class NativeEarlyCheckFailure(RuntimeError):
    """A pre-capture check failed; no capture or picture owner was started."""

    def __init__(self, phase: str, message: str) -> None:
        """Expose the failed phase and category through the delivery receipt."""
        self.phase, self.category = phase, 'early-check-failure'
        super().__init__(message)


def audio_stage_allowance(request: dict) -> tuple[float, float]:
    """The audio owner's own (work, capacity-wait) limits; budget_owner_settings clamps them."""
    return AUDIO_STAGE_WORK_SECONDS, AUDIO_STAGE_CAPACITY_WAIT_SECONDS


def utc() -> str:
    """Record wall-clock order for stage receipts."""
    return datetime.now(timezone.utc).isoformat()


def record_stage(pipeline: object, row: dict, receipt: Path, started: float) -> None:
    """Append one ordered stage row with its receipt binding and elapsed time."""
    row.update(receipt=str(receipt), sha256=digest(receipt) if receipt.is_file() else None,
               elapsedSeconds=time.monotonic() - started, completedAt=utc())
    pipeline.stages.append(row)


def run_early_checks(pipeline: object) -> None:
    """Run static preflight, then prepare or verify sealed audio, before capture."""
    if pipeline.is_long or pipeline.request.get('verifyStage'):
        return
    static_gate(pipeline)
    audio_gate(pipeline)


@contextlib.contextmanager
def admitted_node(node: str) -> Iterator[None]:
    """Lint with the request's admitted Node (as the worker does), then restore the caller's value."""
    previous = os.environ.get('SNIPER_NODE_PATH')
    os.environ['SNIPER_NODE_PATH'] = node
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('SNIPER_NODE_PATH', None)
        else:
            os.environ['SNIPER_NODE_PATH'] = previous


def static_gate(pipeline: object) -> None:
    """Fail a blocked or unverifiable package before any media owner starts."""
    root, request = pipeline.root, pipeline.request
    started, row = time.monotonic(), {'phase': 'static-preflight', 'startedAt': utc()}
    directory = root / STATIC_DIRECTORY
    reference = Path(request['referenceMap']) if request.get('referenceMap') else None
    try:
        with admitted_node(request['tools']['node']), stage_span(str(root), 'native_early_static_preflight'):
            report = preflight(Path(request['project']), directory, reference)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        record_stage(pipeline, {**row, 'status': 'failed'}, directory / 'failure.json', started)
        raise NativeEarlyCheckFailure('static-preflight', f'Native static preflight failed before capture: {error}') \
            from error
    pipeline.evidence.update({str(directory / name): digest(directory / name) for name in STATIC_FILES})
    record_stage(pipeline, {**row, 'status': report['status']}, directory / 'completion.json', started)
    if report['status'] != 'static-checks-pass':
        raise NativeEarlyCheckFailure('static-preflight',
                                      'Native static preflight blocked export before capture; see static/result.json')


def audio_gate(pipeline: object) -> None:
    """Prepare the attempt's own stage, or re-verify a bound sealed stage, then pin it."""
    binding = pipeline.request.get('audioStage')
    if not binding:
        return
    started = time.monotonic()
    row = {'phase': 'audio-stage' if binding['mode'] == 'attempt' else 'audio-stage-reused',
           'startedAt': utc(), 'mode': binding['mode'], 'audioInputSha256': binding['audioInputSha256']}
    if binding['mode'] == 'attempt':
        prepare_attempt_stage(pipeline, row, started)
    seal = Path(binding['seal'])
    record = read_sealed_stage(seal, binding['audioInputSha256'])
    pipeline.evidence.update({record[key]['path']: record[key]['sha256'] for key in SEAL_FILES})
    pipeline.evidence[str(seal)] = digest(seal)
    record_stage(pipeline, {**row, 'status': record['status'], 'masterSha256': record['master']['sha256']},
                 seal, started)


def prepare_attempt_stage(pipeline: object, row: dict, started: float) -> None:
    """Run the supervised audio owner inside this attempt; any failure stops before capture."""
    request, root = pipeline.request, pipeline.root
    work, wait = audio_stage_allowance(request)
    plan = AudioStagePlan(Path(request['project']), root / 'audio-stage', request['audioProfile'],
                          work, wait, Path(request['runtime']), export_request=request)
    try:
        with stage_span(str(root), 'native_owner_audio-stage'):
            prepare_stage(plan, pipeline.environment)
    except AudioStageFailure:
        record_stage(pipeline, {**row, 'status': 'failed'}, plan.root / FAILED_NAME, started)
        raise
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        record_stage(pipeline, {**row, 'status': 'failed'}, plan.root / SEAL_NAME, started)
        raise NativeEarlyCheckFailure('audio-stage', f'Native audio stage failed before capture: {error}') from error


def capture_diagnostics_gate(pipeline: object) -> None:
    """Diagnose captured references before previews; stop a full export on reverse-seek drift.

    The same comparison and thresholds gate the final render later; a preview-only
    run records the finding without blocking editorial previews. Small text never blocks.
    """
    if pipeline.is_long or pipeline.request.get('verifyStage'):
        return
    from studio.native_capture_diagnostics import capture_diagnostics
    started, row = time.monotonic(), {'phase': 'capture-diagnostics', 'startedAt': utc()}
    report = capture_diagnostics(pipeline.root / 'native-frames.json', Path(pipeline.request['project']))
    evidence = pipeline.root / 'capture-diagnostics.json'
    write_new(evidence, report)
    pipeline.evidence[str(evidence)] = digest(evidence)
    reverse = report.get('reverseSeek', {}).get('status')
    record_stage(pipeline, {**row, 'status': report['status'], 'reverseSeek': reverse,
                            'smallTextElements': report.get('phoneText', {}).get('elementCount')}, evidence, started)
    if reverse != 'reverse-seek-stable' and not pipeline.request.get('previewOnly'):
        raise NativeEarlyCheckFailure('reverse-seek', 'Reverse-seek pixel stability failed on captured references '
                                      'before previews and picture; see capture-diagnostics.json')


def worker_static_result(request: dict) -> dict:
    """The in-owner static gate: the early pass while its exact inputs hold, else a fresh preflight.

    A fresh run never reuses the early evidence directory; it writes ``static-render``
    beside it, so no worker phase (render, draft, promotion) collides with the early gate.
    """
    project, root = Path(request['project']), Path(request['output'])
    reference = Path(request['referenceMap']) if request.get('referenceMap') else None
    reused = reusable_static_result(project, root, reference)
    if reused is not None:
        return {**reused, 'evidenceDirectory': str(root / STATIC_DIRECTORY)}
    options = {'reference_map': reference} if reference else {}
    directory = root / ('static-render' if (root / STATIC_DIRECTORY).exists() else STATIC_DIRECTORY)
    return {**preflight(project, directory, **options), 'evidenceDirectory': str(directory)}


def reusable_static_result(project: Path, root: Path, reference_map: Path | None) -> dict | None:
    """Return the early static result only while its exact inputs still hold; else None.

    Args:
        project: The export's canonical project.
        root: The export attempt directory.
        reference_map: The export's explicit reference map, if any.

    Returns:
        The completed early report (pass or blocked) when current, otherwise None.
    """
    directory = root / STATIC_DIRECTORY
    if not directory.exists():
        return None
    report = read_completed(directory)
    recorded = bound_json(directory / 'inputs.json')
    current = {'source': source_state(project), 'tools': validator_state(),
               'referenceMatch': reference_snapshot(project, reference_map)}
    if recorded != current or report['sourceStateSha256'] != current['source']['sourceStateSha256']:
        return None
    return {**report, 'reusedEarlyResult': str(directory)}
