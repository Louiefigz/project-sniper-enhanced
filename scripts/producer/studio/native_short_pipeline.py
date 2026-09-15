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
from studio.native_stage_evidence import StageEvidence, read_stage, seal_stage, require

STUDIO = Path(__file__).resolve().parent
RENDER_STATUS = 'native-short-rendered-awaiting-qc'
FINAL_STATUS = 'native-short-checked-for-review'


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

    def supervise(self, label: str, child: list[str], output: str, status: str) -> None:
        """Keep one heavy lane and the existing 600-second owner budget per stage."""
        sandbox = STUDIO / 'native_localhost_only.sb'
        cli = Path(self.request['runtime']) / 'dist/cli.js'
        request_file = self.root / 'export-request.json'
        settings = NativeRunConfig(Path(self.request['project']), self.root, cli,
            ['/usr/bin/sandbox-exec', '-f', str(sandbox), *child], self.environment,
            {'output': str(self.root / output), 'sdkSha256': digest(cli),
             'sandboxSha256': digest(sandbox)}, sandbox=sandbox,
            compressor_admission='short-headroom', success_status=status,
            additional_pins={**self.request['pins'], **self.evidence,
                             str(request_file): digest(request_file)},
            unused_ram_advisory=self.unused_ram_advisory)
        owner = NativeRun(label, settings)
        with stage_span(str(self.root), f'native_owner_{label}'):
            passed = owner.execute()
        self.stages.append({'phase': label, 'receipt': str(owner.path),
                            'sha256': digest(owner.path), 'status': owner.result['status'],
                            'elapsedSeconds': owner.result['elapsedSeconds']})
        if not passed:
            raise RuntimeError(f'Native {label} failed; preserve this attempt. '
                               'Verification can reuse a completed render-stage.json when available.')
        self.evidence[str(owner.path)] = digest(owner.path)

    def worker(self, phase: str) -> list[str]:
        """Use the same media worker; phases never implement alternate checks."""
        return [sys.executable, str(STUDIO / 'native_short_worker.py'),
                str(self.root / 'export-request.json'), phase]

    def render(self) -> tuple[dict, Path]:
        """Seal newly completed media or read an explicitly supplied existing seal."""
        if self.request.get('verifyStage'):
            record, pins = copy_completed_media(self.request)
            self.evidence.update(pins)
            return record, Path(self.request['verifyStage'])
        self.supervise('pipeline', self.worker('render'), 'review.mp4', RENDER_STATUS)
        artifacts = {'picture': self.root / 'picture.mp4', 'review': self.root / 'review.mp4',
                     'audio': self.root / 'audio/receipt.json', 'media': self.root / 'render-result.json'}
        spec = StageEvidence('render', Path(self.request['project']), self.root,
            self.root / 'export-request.json', self.root / 'pipeline.render.json',
            self.request['pins'], artifacts, RENDER_STATUS)
        seal_stage(spec)
        receipt = self.root / 'render-stage.json'
        record, pins = read_stage(receipt, self.request['pins'], 'render')
        media_result(record)
        self.evidence.update(pins)
        return record, receipt

    def capture(self) -> None:
        """Preserve streaming seek order; retain existing batch phase/compile reuse."""
        if self.request['captureMode'] == 'sdk-streaming':
            child = [self.request['tools']['node'], str(STUDIO / 'native_short_capture.mjs'),
                     str(self.root / 'export-request.json')]
        else:
            child = self.worker('capture')
        self.supervise('capture', child, 'native-frames.json', 'native-reference-capture-complete')
        file = self.root / 'native-frames.json'
        sha = digest(file)
        native = bound_json(file, sha)
        require(native.get('status') == 'native-references-and-seek-states-pass',
                'native reference checks did not pass')
        self.evidence[str(file)] = sha

    def verify(self, expected: str) -> dict:
        """Expose a checked result only after encoded QC and its owned cleanup."""
        self.supervise('verification', self.worker('verify'), 'checks.json', FINAL_STATUS)
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
            record, receipt = self.render()
            result['renderStage'] = str(receipt)
            expected = record['artifacts']['review']['sha256']
            if render_only:
                result.update(status=RENDER_STATUS, sha256=expected)
            else:
                self.evidence[str(self.root / 'review.mp4')] = expected
                self.capture()
                result.update(self.verify(expected), status=FINAL_STATUS)
        except (Exception, KeyboardInterrupt) as error:
            result.update(status='failed', errorType=type(error).__name__, error=str(error))
        result.update(completedAt=utc(), elapsedSeconds=time.monotonic() - started, stages=self.stages)
        write_new(self.root / 'delivery.json', result)
        print(json.dumps(result), flush=True)
        return result['status'] in {RENDER_STATUS, FINAL_STATUS}
