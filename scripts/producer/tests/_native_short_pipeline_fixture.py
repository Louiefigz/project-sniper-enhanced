"""TEST-only native media/owner fixtures; no executable or quality qualification."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE
from studio.native_run_config import source_hashes
from studio.native_runtime import digest
from studio.native_short_pipeline import RENDER_STATUS
from studio.native_stage_evidence import STABLE_FIELDS, StageEvidence, seal_stage


def write_json(path: Path, value: dict) -> None:
    """Write fixture data, never a claim of actual native media execution."""
    path.write_text(json.dumps(value))


STUDIO = Path(__file__).resolve().parents[1] / 'studio'


class ShortPipelineFixture:
    """Real filesystem and shared stage seals with explicitly fake child results."""

    def __init__(self, base: Path) -> None:
        """Create distinct source, project, tools and fresh output directories."""
        self.base, self.project, self.root = base, base / 'project', base / 'original'
        self.project.mkdir()
        self.root.mkdir()
        self.runtime = base / 'runtime'
        (self.runtime / 'dist').mkdir(parents=True)
        self.cli, self.node = self.runtime / 'dist/cli.js', base / 'node'
        self.cli.write_text('TEST fake CLI, never executed')
        self.node.write_text('TEST fake node, never executed')
        (self.runtime / 'dist/native-capture-library.mjs').write_text('TEST capture library')
        self.source = base / 'source.mp4'
        self.source.write_bytes(b'TEST source media, not decodable')
        (self.project / 'index.html').write_text('<p>TEST composition</p>')
        write_json(self.project / 'SHORT-PROJECT.json', {
            'canvas': {'frameRate': '25/1', 'totalFrames': 25},
            'strategy': {'schemaVersion': 2}, 'assets': []})
        self.inputs = {str(file): digest(file) for file in (
            self.cli, self.node, self.source, *self.project.iterdir(),
            self.runtime / 'dist/native-capture-library.mjs', Path(sys.executable).resolve(),
            STUDIO / 'native_short_capture.mjs', STUDIO / 'native_short_worker.py',
            STUDIO / 'native_localhost_only.sb')}
        self.request = {'schemaVersion': 1, 'project': str(self.project), 'output': str(self.root),
                        'runtime': str(self.runtime), 'tools': {'node': str(self.node)},
                        'cache': str(base / 'cache'), 'captureMode': 'sdk-streaming',
                        'sourceCacheMode': 'existing-only', 'audioDonor': None, 'pictureDonor': None,
                        'audioProfile': NATIVE_SHORT_MASTERING_PROFILE.identity, 'pins': self.inputs}
        self.calls: list[tuple[str, object]] = []
        self.failures: dict[str, BaseException | bool] = {}
        self.capture_status = 'native-references-and-seek-states-pass'
        self.write_request(self.request)

    def write_request(self, request: dict) -> None:
        """Write one exclusive-attempt request before constructing its pipeline."""
        write_json(Path(request['output']) / 'export-request.json', request)

    def write_media(self, root: Path) -> dict:
        """Produce tiny media placeholders and consistent audio/color proof fields."""
        (root / 'picture.mp4').write_bytes(b'TEST encoded picture')
        (root / 'review.mp4').write_bytes(b'TEST encoded final audio and picture')
        (root / 'audio').mkdir()
        audio = {'status': 'audio-qualified', 'audioQuality': [], 'audioReviewRequired': False}
        write_json(root / 'audio/receipt.json', audio)
        color = {'output': str(root / 'review.mp4'), 'sha256': digest(root / 'review.mp4'),
                 'aacPacketsIdentical': True, 'additionalPictureEncodes': 0,
                 'additionalAudioEncodes': 0}
        media = {'status': 'media-complete-awaiting-qc', **color,
                 'audioReceipt': str(root / 'audio/receipt.json'),
                 'audioQuality': [], 'audioReviewRequired': False, 'color': color,
                 'humanApproved': False, 'additionalPictureEncodes': 1, 'providerCalls': 0}
        write_json(root / 'render-result.json', media)
        return media

    def owner_record(self, request: dict, pins: dict, status: str, output: str) -> dict:
        """Model a completed TEST owner for exercising real stage validators."""
        return {'status': status, 'elapsedSeconds': 0.01, 'exitCode': 0,
                'project': request['project'], 'output': output, 'pid': 101, 'abortReason': None,
                'ownerIdentities': [{'pid': 101, 'pgid': 101, 'parent_pid': 100, 'started': 'TEST'}],
                'cleanup': {'verified': True, 'survivors': []},
                'sourceHashesBefore': source_hashes(Path(request['project'])),
                'sourceHashesAfter': source_hashes(Path(request['project'])),
                'additionalFilePinsBefore': dict(pins), 'additionalFilePinsAfter': dict(pins),
                **{name: True for name in STABLE_FIELDS}}

    def owner_factory(self, label: str, settings: object) -> SimpleNamespace:
        """Replace only NativeRun execution, retaining actual config and coordinator."""
        owner = SimpleNamespace(path=settings.root / f'{label}.render.json', result={})

        def execute() -> bool:
            """Record ordered TEST owners and fabricate only the requested child outputs."""
            self.calls.append((label, settings))
            request = json.loads((settings.root / 'export-request.json').read_text())
            failure = self.failures.get(label)
            status = 'failed' if failure is not None else settings.success_status
            owner.result = self.owner_record(request, settings.additional_pins, status,
                                             settings.admission['output'])
            owner.result['args'] = list(settings.command)
            write_json(owner.path, owner.result)
            if isinstance(failure, BaseException):
                raise failure
            if failure is not None:
                return False
            self.write_phase(label, settings.root)
            return True

        owner.execute = execute
        return owner

    def write_phase(self, label: str, root: Path) -> None:
        """Model native phase artifacts without calling a renderer, decoder or browser."""
        if label == 'pipeline':
            self.write_media(root)
        elif label == 'capture':
            self.write_capture(root)
        elif label == 'verification':
            write_json(root / 'checks.json', {'status': 'checks-passed-awaiting-owned-cleanup',
                'sha256': digest(root / 'review.mp4'), 'fullAudioVideoDecodePassed': True})

    def write_capture(self, root: Path) -> None:
        """Emit bounded TEST forward/reverse JPEG bindings for real recovery admission."""
        rows = []
        for index, frame in enumerate([0, 24, 0]):
            image = root / f'pose-{index}.jpg'
            image.write_bytes(f'TEST JPEG {frame}'.encode())
            rows.append({'frame': frame, 'path': str(image), 'sha256': digest(image), 'repeat': index == 2})
        write_json(root / 'native-frames.json', {'status': self.capture_status, 'frames': rows,
            'fromEncodedOutput': False, 'project': str(self.project), 'failedSceneStates': [],
            'width': 1080, 'height': 1920, 'frameRate': '25/1', 'expectedCapturePoints': [0, 24, 0],
            'sourceHtmlSha256': digest(self.project / 'index.html'),
            'runtimeLibrarySha256': digest(self.runtime / 'dist/native-capture-library.mjs')})

    def seal(self) -> Path:
        """Create a valid TEST completed stage for the real resume admission path."""
        self.write_media(self.root)
        request_file = self.root / 'export-request.json'
        pins = {**self.inputs, str(request_file): digest(request_file)}
        owner_file = self.root / 'pipeline.render.json'
        write_json(owner_file, self.owner_record(self.request, pins, RENDER_STATUS,
                                                 str(self.root / 'review.mp4')))
        artifacts = {'picture': self.root / 'picture.mp4', 'review': self.root / 'review.mp4',
                     'audio': self.root / 'audio/receipt.json', 'media': self.root / 'render-result.json'}
        seal_stage(StageEvidence('render', self.project, self.root, request_file,
                                 owner_file, self.inputs, artifacts, RENDER_STATUS))
        return self.root / 'render-stage.json'

    def current(self, output: Path | None = None) -> dict:
        """Return current dependencies for a new verification invocation."""
        return {**self.request, 'output': str(output or self.base / 'verification'),
                'pins': dict(self.inputs)}

    def options(self, **changes: object) -> Namespace:
        """Provide the full CLI namespace without parsing or launching a command."""
        values = {'project': self.project, 'output': self.base / 'verification', 'cache': None,
                  'audio_donor': None, 'picture_donor': None, 'cached_native_batches': False,
                  'acquire_source_cache': False, 'audio_profile': NATIVE_SHORT_MASTERING_PROFILE.identity,
                  'verify_from': None, 'render_only': False, 'unused_ram_advisory': False}
        return Namespace(**{**values, **changes})

    def terminal(self, status: str = 'failed', root: Path | None = None) -> None:
        """Record fictional terminal discovery state, separately from actual stage authority."""
        write_json((root or self.root) / 'delivery.json',
                   {'status': status, 'completedAt': '2026-09-16T12:00:00Z'})

    def partial_audio(self) -> Path:
        """Retain a TEST float master with a clean failed original render owner."""
        directory = self.root / 'audio-preparation'
        directory.mkdir()
        master, receipt = directory / 'program-master.wav', directory / 'receipt.json'
        master.write_bytes(b'TEST float master')
        write_json(receipt, {'status': 'float-master-checked-awaiting-aac', 'masterSha256': digest(master)})
        file = self.root / 'export-request.json'
        pins = {**self.inputs, str(file): digest(file)}
        owner = self.owner_record(self.request, pins, 'failed', str(self.root / 'review.mp4'))
        owner.update(exitCode=1, args=['/usr/bin/sandbox-exec', '-f', str(STUDIO / 'native_localhost_only.sb'),
                                     sys.executable, str(STUDIO / 'native_short_worker.py'), str(file), 'render'])
        write_json(self.root / 'pipeline.render.json', owner)
        self.terminal()
        return receipt
