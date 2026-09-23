"""Run render, native capture and encoded QC as separate bounded native owners."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from cut_preview_io import bound_json, write_new
from stage_timing import stage_span
from studio.native_run import NativeRun, utc
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from studio.native_short_resume import copy_completed_media, media_result
from studio.native_short_capture_resume import copy_completed_capture, complete_capture, capture_artifacts, CAPTURE_STATUS
from studio.native_stage_evidence import (
    StageEvidence, read_native_capture_receipt, read_stage, seal_stage, require,
)

STUDIO = Path(__file__).resolve().parent
RENDER_STATUS = 'native-short-rendered-awaiting-qc'
FINAL_STATUS = 'native-short-checked-for-review'


class NativeStageFailure(RuntimeError):
    """Carry the original owner failure without conflating pressure and missing samples."""

    def __init__(self, phase: str, result: dict) -> None:
        """Preserve the failed owner's category and phase for the delivery receipt."""
        self.category = result.get('failureCategory') or 'renderer-failure'
        self.phase = phase
        super().__init__(f"Native {phase} failed ({self.category}): {result.get('abortReason') or 'worker failed'}. "
                         'Preserve this attempt; completed section seals are reusable on the next invocation.')


@dataclass
class NativeShortPipeline:
    """One invocation with immutable inputs and new per-phase owners on the main thread."""

    request: dict
    environment: dict[str, str]
    unused_ram_advisory: bool = False
    stages: list[dict] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        """Return the fresh attempt directory."""
        return Path(self.request['output'])

    @property
    def is_long(self) -> bool:
        """Keep one lifecycle while selecting the landscape contract explicitly."""
        return self.request.get('adapter') == 'native-long'

    def supervise(self, label: str, child: list[str], output: str, status: str) -> None:
        """Keep one heavy lane with explicit stage and bounded queue budgets."""
        sandbox = STUDIO / 'native_localhost_only.sb'
        cli = Path(self.request['runtime']) / 'dist/cli.js'
        request_file = self.root / 'export-request.json'
        budget = self.request.get('budget', {}) if self.is_long else {}
        deadline = budget.get('ownerSeconds', 600) if label in {'pipeline', 'picture'} else budget.get(
            'sampleSeconds' if label in {'capture', 'preview'} else 'verificationSeconds', 600)
        settings = NativeRunConfig(Path(self.request['project']), self.root, cli,
            ['/usr/bin/sandbox-exec', '-f', str(sandbox), *child], self.environment,
            {'output': str(self.root / output), 'sdkSha256': digest(cli),
             'sandboxSha256': digest(sandbox)}, sandbox=sandbox,
            compressor_admission='short-headroom', success_status=status,
            additional_pins={**self.request['pins'], **self.evidence,
                             str(request_file): digest(request_file)},
            unused_ram_advisory=self.unused_ram_advisory)
        if self.is_long or label.startswith('preview-'):
            from dataclasses import replace
            settings = replace(settings, deadline=deadline + 600, idle_deadline=budget.get('idleSeconds', 120),
                               capacity_wait_seconds=600)
        owner = NativeRun(label, settings)
        with stage_span(str(self.root), f'native_owner_{label}'):
            passed = owner.execute()
        self.stages.append({'phase': label, 'receipt': str(owner.path),
                            'sha256': digest(owner.path), 'status': owner.result['status'],
                            'elapsedSeconds': owner.result['elapsedSeconds']})
        if not passed:
            raise NativeStageFailure(label, owner.result)
        self.evidence[str(owner.path)] = digest(owner.path)

    def worker(self, phase: str) -> list[str]:
        """Use the same media worker; phases never implement alternate checks."""
        worker = 'native_long_worker.py' if self.is_long else 'native_short_worker.py'
        return [sys.executable, str(STUDIO / worker),
                str(self.root / 'export-request.json'), phase]

    def render(self) -> tuple[dict, Path]:
        """Seal newly completed media or read an explicitly supplied existing seal."""
        if self.request.get('verifyStage'):
            record, pins = copy_completed_media(self.request)
            self.evidence.update(pins)
            return record, Path(self.request['verifyStage'])
        if self.is_long:
            from studio.native_long_recovery import ensure_picture
            ensure_picture(self)
        status = 'native-long-rendered-awaiting-qc' if self.is_long else RENDER_STATUS
        self.supervise('pipeline', self.worker('render'), 'review.mp4', status)
        artifacts = {'picture': self.root / 'picture.mp4', 'review': self.root / 'review.mp4',
                     'audio': self.root / 'audio/receipt.json', 'media': self.root / 'render-result.json'}
        spec = StageEvidence('render', Path(self.request['project']), self.root,
            self.root / 'export-request.json', self.root / 'pipeline.render.json',
            self.request['pins'], artifacts, status)
        seal_stage(spec)
        receipt = self.root / 'render-stage.json'
        record, pins = read_stage(receipt, self.request['pins'], 'render')
        media_result(record)
        self.evidence.update(pins)
        return record, receipt

    def capture(self) -> None:
        """Preserve streaming seek order; retain existing batch phase/compile reuse."""
        if self.request.get('captureStage'):
            _record, pins = copy_completed_capture(self.request)
            self.evidence.update(pins)
            receipt = Path(self.request['captureStage'])
            self.stages.append({'phase': 'capture-reused', 'receipt': str(receipt),
                'sha256': digest(receipt), 'status': CAPTURE_STATUS, 'elapsedSeconds': 0,
                'additionalCaptureFrames': 0})
            return
        if self.is_long:
            child = self.worker('capture')
        elif self.request['captureMode'] == 'sdk-streaming':
            child = [self.request['tools']['node'], str(STUDIO / 'native_short_capture.mjs'),
                     str(self.root / 'export-request.json')]
        else:
            child = self.worker('capture')
        self.supervise('capture', child, 'native-frames.json', 'native-reference-capture-complete')
        file = self.root / 'native-frames.json'
        sha = digest(file)
        native = read_native_capture_receipt(file, sha)
        require(native.get('status') == 'native-references-and-seek-states-pass',
                'native reference checks did not pass')
        self.evidence[str(file)] = sha
        if not self.request.get('verifyStage'):
            self.evidence.update({str(path): digest(path) for path in capture_artifacts(self.root, self.request).values()})
            return  # This same checked full-context capture gates the master.
        render_stage = Path(self.request.get('verifyStage') or self.root / 'render-stage.json')
        _receipt, pins = complete_capture(self.root, render_stage)
        self.evidence.update(pins)

    def verify(self, expected: str) -> dict:
        """Expose a checked result only after encoded QC and its owned cleanup."""
        status = 'native-long-checked-for-review' if self.is_long else FINAL_STATUS
        self.supervise('verification', self.worker('verify'), 'checks.json', status)
        checks = bound_json(self.root / 'checks.json')
        require(checks.get('status') == 'checks-passed-awaiting-owned-cleanup'
                and checks.get('sha256') == expected == digest(self.root / 'review.mp4')
                and checks.get('fullAudioVideoDecodePassed') is True,
                'final encoded verification is incomplete or media changed')
        return checks

    def execute(self, render_only: bool = False, invocation: tuple[float, str] | None = None) -> bool:
        """Record the whole invocation, including failed stages and reused media."""
        phase_start = time.monotonic()
        started, began = invocation or (phase_start, utc())
        result = {'status': 'failed', 'startedAt': began, 'renderReused': bool(self.request.get('verifyStage')),
                  'output': str(self.root / 'review.mp4'), 'humanApproved': False,
                  'preparationSeconds': phase_start - started,
                  'timingScope': 'This export invocation including preparation and all owners; editorial authoring is separate.'}
        try:
            if not self.request.get('verifyStage'):
                self.capture()
                previews = self.preview()
                if self.request.get('previewOnly'):
                    result.update(status='native-motion-previews-complete',
                                  output=str(self.root / 'motion-previews.json'),
                                  previews=previews, editorialReview='pending',
                                  nextStep='Inspect the moving previews, record independent region reviews, then rerun with --preview-reviews.')
                    return self.complete(result, started)
            record, receipt = self.render()
            result['renderStage'] = str(receipt)
            expected = record['artifacts']['review']['sha256']
            if render_only:
                result.update(status=RENDER_STATUS, sha256=expected)
            else:
                self.evidence[str(self.root / 'review.mp4')] = expected
                if not self.request.get('verifyStage'):
                    _receipt, pins = complete_capture(self.root, receipt)
                    self.evidence.update(pins)
                else:
                    self.capture()
                result['captureStage'] = str(self.request.get('captureStage') or self.root / 'capture-stage.json')
                result.update(self.verify(expected), status='native-long-checked-for-review' if self.is_long else FINAL_STATUS)
        except (Exception, KeyboardInterrupt) as error:
            result.update(status='failed', errorType=type(error).__name__, error=str(error),
                          failureCategory='cancelled' if isinstance(error, KeyboardInterrupt)
                          else getattr(error, 'category', 'renderer-failure'),
                          failedPhase=getattr(error, 'phase', None))
        return self.complete(result, started)

    def preview(self) -> dict:
        """Retain continuous picture/audio checks before any full picture owner starts."""
        from studio.native_motion_previews import STATUS
        from studio.native_preview_sections import prepare_sections
        prepare_sections(self)
        self.supervise('preview', self.worker('preview'), 'motion-previews.json', STATUS)
        file = self.root / 'motion-previews.json'
        previews = bound_json(file)
        require(previews.get('status') == STATUS, 'Continuous preview preparation failed')
        self.evidence[str(file)] = digest(file)
        self.evidence.update({row['path']: row['sha256'] for row in previews['clips']})
        return previews

    def complete(self, result: dict, started: float) -> bool:
        """Publish exactly one terminal receipt for successful and failed invocations."""
        result.update(completedAt=utc(), elapsedSeconds=time.monotonic() - started, stages=self.stages)
        write_new(self.root / 'delivery.json', result)
        print(json.dumps(result), flush=True)
        return result['status'] in {RENDER_STATUS, FINAL_STATUS, 'native-long-checked-for-review',
                                    'native-motion-previews-complete'}
