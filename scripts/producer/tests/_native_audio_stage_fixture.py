"""TEST-only audio-stage fixtures: real contracts, receipts and seals around inert bytes.

No DSP, FFmpeg or listening happens here. Fake owners run the real stage worker
in-process with a patched ``prepare_dialogue`` that writes clearly synthetic files;
every seal/reader/import check under test is the production code. The worker's live-owner
gate is never weakened: fake owners publish an explicit TEST launch receipt and hand the
worker the real shared binding from ``native_export.worker_environment``.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from audio.mastering_profile import resolve_mastering_profile
from cut_preview_io import file_hash
from producer_config import MASTERING_POLICY_VERSION
from studio.native_audio_seal import OWNER_NAME
from studio.native_export import BINDING_ENV, worker_environment
from studio.native_short_delivery import dialogue_review_sections
from studio.native_short_dialogue import clock
from studio.native_stage_evidence import STABLE_FIELDS

SOURCE = 'assets/' + '5' * 64 + '.mp4'
FINISHING = {'schemaVersion': 1, 'audioEnhance': {'preset': 'voice-rnn'},
             'rationale': 'TEST source-specific cleanup rationale; no listening occurred.'}


def write_json(path: Path, value: object) -> None:
    """Persist synthetic TEST data, never production evidence."""
    path.write_text(json.dumps(value))


def canvas(start: float = 10.5, frames: int = 150) -> dict:
    """One-cut 30 fps TEST canvas with presentation fields that audio must ignore."""
    return {'title': 'TEST title', 'frameRate': '30/1', 'totalFrames': frames, 'sourceFile': SOURCE,
            'cuts': [{'start': start, 'end': start + frames / 30, 'speed': 1}],
            'segments': [{'startFrame': 0, 'endFrameExclusive': frames}],
            'pictureViews': [{'startFrame': 0, 'endFrame': 105, 'crop': [70, 0, 720, 1080], 'box': [0, 0, 1080, 1620]}],
            'captionViews': [{'startFrame': 0, 'endFrame': frames, 'box': [120, 1660, 840, 160]}]}


class AudioProjectFixture:
    """A prepared-sources native project whose dialogue bytes are inert TEST data."""

    def __init__(self, base: Path, name: str = 'project') -> None:
        """Create tools and one project with a single prepared dialogue WAV."""
        self.base = base
        self.tools = {'ffmpeg': str(base / 'TEST-ffmpeg'), 'ffprobe': str(base / 'TEST-ffprobe'),
                      'node': str(base / 'TEST-node')}
        for value in self.tools.values():
            Path(value).write_text('TEST tool bytes; never executed')
        self.package = base / 'TEST-package.json'
        self.package.write_text('{"TEST": "prepared-source package binding only"}')
        self.project = self.write(base / name)

    def write(self, project: Path, **changes: object) -> Path:
        """Author one project; keyword changes replace canvas/plan/dialogue fields."""
        project.mkdir()
        (project / 'assets').mkdir()
        start = changes.get('start', 10.5)
        value = changes.get('canvas') or canvas(start, changes.get('frames', 150))
        wav = project / 'assets/TEST-dialogue-0.wav'
        wav.write_bytes(changes.get('dialogue', b'TEST dialogue PCM placeholder; not decodable'))
        binding = {'path': str(self.package), 'sha256': file_hash(self.package)}
        mapping = {'id': 'dialogue-0', 'kind': 'audio', 'sourceFile': SOURCE, 'start': start,
                   'end': start + value['totalFrames'] / 30, 'sourceOrigin': str(start - 1),
                   'mediaStart': 1.0, 'preparedFile': 'assets/TEST-dialogue-0.wav'}
        plan = {'canvas': value, 'preparedSources': binding, **changes.get('plan', {})}
        if 'audioFinishing' not in changes.get('plan', {}):
            plan['audioFinishing'] = FINISHING
        write_json(project / 'SHORT-PROJECT.json', {key: item for key, item in plan.items() if item is not None})
        write_json(project / 'PREPARED-SOURCES.json', {'package': binding, 'mappings': [mapping]})
        write_json(project / 'PROJECT-MANIFEST.json', {'files': [
            {'file': 'assets/TEST-dialogue-0.wav', 'sha256': file_hash(wav)}]})
        (project / 'index.html').write_text('<p>TEST inert composition</p>')
        return project


def fake_prepare_dialogue(request: dict, value: dict, finishing: object) -> dict:
    """Write synthetic premaster/master files with a real-format prepared master receipt."""
    work = Path(request['output'])
    (work / 'dialogue-cleanup').mkdir()
    (work / 'audio-preparation').mkdir()
    (work / 'reference.wav').write_bytes(b'TEST raw reference PCM')
    premaster = work / 'dialogue-cleanup/dialogue-finished.wav'
    premaster.write_bytes(b'TEST finished premaster PCM')
    master = work / 'audio-preparation/program-master.wav'
    master.write_bytes(b'TEST float master PCM')
    profile = resolve_mastering_profile(request['audioProfile'])
    receipt = work / 'audio-preparation/receipt.json'
    write_json(receipt, {'schemaVersion': 1, 'status': 'float-master-checked-awaiting-aac',
        'humanListeningApproved': False, 'inputPremasterSha256': file_hash(premaster),
        'samples': clock(value).sample_at_frame(value['totalFrames']), 'masteringProfile': profile.receipt(),
        'reviewSections': list(dialogue_review_sections(value)), 'additionalAacEncodes': 0,
        'premasterClock': {}, 'masteringFilter': 'TEST', 'masteringNote': None,
        'masteringPolicyVersion': MASTERING_POLICY_VERSION, 'masterClock': {},
        'masterDelivery': {'qualified': True}, 'masterSha256': file_hash(master),
        'audioQuality': [{'name': 'audio_tonal_hum', 'status': 'pass', 'measured': 'TEST', 'detail': ''}],
        'audioReviewRequired': False, 'output': str(master)})
    return {'kind': 'master', 'reference': str(premaster), 'referenceSha256': file_hash(premaster),
            'masterReceipt': str(receipt), 'masterReceiptSha256': file_hash(receipt), 'audioFinishing': finishing}


def launch_receipt(settings: object, **changes: object) -> dict:
    """TEST authority: the receipt a live, admitted owner has published when its child starts.

    Keyword changes replace fields, so tests can model foreign, stale or unadmitted owners.
    """
    pins = {path: file_hash(Path(path), 1024 ** 4) for path in settings.additional_pins}
    receipt = {'status': 'running', 'project': str(settings.project), 'output': settings.admission['output'],
               'args': list(settings.command), 'additionalFilePinsBefore': pins, 'pid': os.getpid(),
               'supervisorPid': os.getpid(), 'productionAllocation': settings.hard_deadline,
               'pool': {'class': settings.lane, 'TEST': 'fixture admission; no host pool member'},
               'queue': {'admitted': True}, 'runDeadlineSeconds': settings.deadline}
    return {**receipt, **changes}


@contextlib.contextmanager
def supervised(settings: object, owner_file: Path, environment: dict | None = None,
               parent: int | None = None) -> Iterator[None]:
    """Give the in-process worker the real shared binding; model this process as its parent.

    Args:
        settings: The stage owner's real NativeRunConfig.
        owner_file: The owner receipt the binding names.
        environment: Binding variables to replace (a None value removes one).
        parent: The modeled parent PID; defaults to this supervising process.
    """
    binding = {key: value for key, value in worker_environment(settings, owner_file).items() if key in BINDING_ENV}
    binding.update(environment or {})
    modeled = os.getpid() if parent is None else parent
    with mock.patch.dict(os.environ), mock.patch('os.getppid', return_value=modeled):
        for key in BINDING_ENV:
            os.environ.pop(key, None)
        os.environ.update({key: value for key, value in binding.items() if value is not None})
        yield


def owner_factory(worker: object) -> object:
    """Return a NativeRun stand-in that runs the real stage worker in-process under TEST authority."""
    def build(label: str, settings: object) -> SimpleNamespace:
        """Stand in for one NativeRun built from the stage's real settings."""
        owner = SimpleNamespace(path=settings.root / OWNER_NAME, result={})

        def execute() -> bool:
            """Publish the launch receipt, run the gated worker, then publish the completed receipt."""
            launch = launch_receipt(settings)
            write_json(owner.path, launch)
            try:
                with supervised(settings, owner.path):
                    worker(Path(settings.command[-1]))
                passed = True
            except Exception as error:  # the real owner records any child failure
                passed, owner.error = False, error
            after = {path: file_hash(Path(path), 1024 ** 4) for path in settings.additional_pins}
            owner.result = {**launch, 'status': settings.success_status if passed else 'failed',
                'exitCode': 0 if passed else 1, 'completedAt': 'TEST', 'elapsedSeconds': 0.01,
                'abortReason': None if passed else 'TEST worker failed',
                'failureCategory': None if passed else 'renderer-failure', 'label': label,
                'cleanup': {'verified': True, 'survivors': []}, 'additionalFilePinsAfter': after,
                **{name: True for name in STABLE_FIELDS}}
            write_json(owner.path, owner.result)
            return passed
        owner.execute = execute
        return owner
    return build


def copy_tree(source: Path, target: Path) -> None:
    """Copy a TEST project to another path without links."""
    shutil.copytree(source, target, symlinks=False)
