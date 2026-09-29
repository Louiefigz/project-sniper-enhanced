"""Final family settlement reopens authentic proof structure; TEST media is nondecodable."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import test_native_budget_family_admission as admission
from cut_preview_io import write_new
from studio.native_budget_family_delivery import require_checked_media
from studio.native_runtime import digest
from studio.native_short_capture_resume import complete_capture
from studio.native_stage_evidence import StageEvidence, seal_stage, read_stage


class FamilyDeliveryTests(unittest.TestCase):
    """Exercise real existing seal readers and owned verification without claiming codec checks."""

    def setUp(self) -> None:
        self.h = admission.FamilyAdmissionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.request = self.h.reserve('first', False)
        self.root = Path(self.request['output'])
        from studio import native_long_worker
        self.studio = Path(native_long_worker.__file__).parent
        for file in (self.studio / 'native_long_worker.py', self.studio / 'native_localhost_only.sb',
                     Path(sys.executable).resolve(strict=True)):
            self.request['pins'][str(file)] = digest(file)
        (self.root / 'export-request.json').write_text(json.dumps(self.request))
        self.result = {'status': 'native-long-checked-for-review', 'output': str(self.root / 'review.mp4')}

    def owner(self, phase: str, status: str, output: Path, pins: dict) -> dict:
        file = self.root / 'export-request.json'
        owner = self.h.h.fixture.owner_record(self.request, {**self.request['pins'], **pins, str(file): digest(file)},
                                              status, str(output))
        owner['args'] = ['/usr/bin/sandbox-exec', '-f', str(self.studio / 'native_localhost_only.sb'),
                         sys.executable, str(self.studio / 'native_long_worker.py'), str(file), phase]
        return owner

    def media(self) -> dict:
        fixture = self.h.h.fixture
        fixture.write_media(self.root)
        status = 'native-long-rendered-awaiting-qc'
        write_new(self.root / 'pipeline.render.json', self.owner('render', status, self.root / 'review.mp4', {}))
        artifacts = {'picture': self.root / 'picture.mp4', 'review': self.root / 'review.mp4',
                     'audio': self.root / 'audio/receipt.json', 'media': self.root / 'render-result.json'}
        seal_stage(StageEvidence('render', Path(self.request['project']), self.root,
            self.root / 'export-request.json', self.root / 'pipeline.render.json', self.request['pins'], artifacts, status))
        self.result['sha256'] = digest(self.root / 'review.mp4')
        return read_stage(self.root / 'render-stage.json', self.request['pins'], 'render')[1]

    def capture(self) -> dict:
        self.h.h.fixture.write_capture(self.root)
        file = self.root / 'native-frames.json'
        capture = json.loads(file.read_text())
        capture.update(width=320, height=180)
        file.write_text(json.dumps(capture))
        for name in ('sample-qc/result.json', 'audio-preparation/receipt.json',
                     'audio-preparation/program-master.wav', 'prepared-audio.json'):
            file = self.root / name
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(b'TEST capture evidence')
        write_new(self.root / 'capture.render.json', self.owner('capture', 'native-reference-capture-complete',
                                                               self.root / 'native-frames.json', {}))
        return complete_capture(self.root, self.root / 'render-stage.json')[1]

    def proof(self) -> None:
        media = self.media()
        capture = self.capture()
        write_new(self.root / 'checks.json', {'status': 'checks-passed-awaiting-owned-cleanup',
                  'sha256': self.result['sha256'], 'fullAudioVideoDecodePassed': True})
        write_new(self.root / 'verification.render.json', self.owner('verify', self.result['status'],
                  self.root / 'checks.json', {**media, **capture}))

    def test_checked_receipt_alone_cannot_complete_family(self) -> None:
        write_new(self.root / 'delivery.json', self.result)
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            require_checked_media(self.request, self.result)

    def test_real_proof_chain_is_required_and_changed_review_or_cleanup_refuses(self) -> None:
        self.proof()
        require_checked_media(self.request, self.result)
        media = self.root / 'review.mp4'
        before = media.read_bytes()
        media.write_bytes(b'TEST changed delivered media')
        with self.assertRaises((ValueError, RuntimeError)):
            require_checked_media(self.request, self.result)
        media.write_bytes(before)
        file = self.root / 'verification.render.json'
        owner = json.loads(file.read_text())
        owner['cleanup']['verified'] = False
        file.write_text(json.dumps(owner))
        with self.assertRaisesRegex((ValueError, RuntimeError), 'cleanup'):
            require_checked_media(self.request, self.result)

    def test_verifier_cannot_omit_capture_dependency_or_substitute_worker(self) -> None:
        self.proof()
        file = self.root / 'verification.render.json'
        owner = json.loads(file.read_text())
        original = json.dumps(owner)
        for key in ('additionalFilePinsBefore', 'additionalFilePinsAfter'):
            owner[key].pop(str(self.root / 'capture-stage.json'))
        file.write_text(json.dumps(owner))
        with self.assertRaisesRegex((ValueError, RuntimeError), 'closure'):
            require_checked_media(self.request, self.result)
        owner = json.loads(original)
        owner['args'][-1] = 'render'
        file.write_text(json.dumps(owner))
        with self.assertRaisesRegex((ValueError, RuntimeError), 'worker'):
            require_checked_media(self.request, self.result)


if __name__ == '__main__':
    unittest.main()
