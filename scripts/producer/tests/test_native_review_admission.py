"""Admit real shared TEST seals for original and resumed native review exports."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _native_short_pipeline_fixture import ShortPipelineFixture, write_json
from studio import native_review_contract as review
from studio.native_short_capture_resume import seal_capture
from studio.native_short_resume import prepare_reverification
from studio.native_short_picture_reuse import copy_picture
from studio.native_runtime import digest
from test_native_review_html import fixture


class NativeReviewAdmissionTests(unittest.TestCase):
    """Filesystem evidence rejects stale, missing, wrong and changed review origins."""

    def setUp(self) -> None:
        """Create isolated source files and evidence for the test."""
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.f = ShortPipelineFixture(base)
        html, canvas = fixture(); html = html.replace('data-width="1920" data-height="1080"', 'data-width="1080" data-height="1920"')
        (self.f.project / 'index.html').write_text(html)
        write_json(self.f.project / 'SHORT-PROJECT.json', {'canvas': canvas})
        write_json(self.f.project / 'hyperframes.json', {'media': {'autoProxy': True}})
        self.library = self.f.runtime / 'dist/native-capture-library.mjs'; self.library.write_text('TEST native library')
        paths = [*self.f.project.iterdir(), self.library, self.f.node, self.f.cli, self.f.source, Path(sys.executable).resolve(),
                 review.Path(__file__).resolve().parents[1] / 'studio/native_short_capture.mjs',
                 review.Path(__file__).resolve().parents[1] / 'studio/native_localhost_only.sb']
        self.f.inputs.clear(); self.f.inputs.update({str(file): digest(file) for file in paths})
        files = [{'file': p.name, 'sha256': digest(p)} for p in self.f.project.iterdir()]
        manifest = self.f.project / 'PROJECT-MANIFEST.json'; write_json(manifest, {'files': files})
        self.f.inputs[str(manifest)] = digest(manifest)
        self.f.write_request(self.f.request); self.render = self.f.seal()
        self.capture(self.f.root, self.f.request)
        self.finalize(self.f.root, self.f.request)

    def capture(self, root: Path, request: dict) -> None:
        """Use actual shared stage sealing around tiny fictional JPEG content."""
        rows = []
        for index, frame in enumerate([0, 24, 0]):
            path = root / f'pose-{index}.jpg'; path.write_bytes(b'TEST JPEG bytes')
            rows.append({'frame': frame, 'repeat': index == 2, 'path': str(path), 'sha256': digest(path)})
        file = root / 'native-frames.json'
        write_json(file, {'status': 'native-references-and-seek-states-pass', 'fromEncodedOutput': False,
            'project': str(self.f.project), 'failedSceneStates': [], 'width': 1080, 'height': 1920, 'frameRate': '25/1',
            'sourceHtmlSha256': digest(self.f.project / 'index.html'), 'runtimeLibrarySha256': digest(self.library),
            'expectedCapturePoints': [0, 24, 0], 'frames': rows})
        request_file = root / 'export-request.json'; pins = {**request['pins'], str(request_file): digest(request_file)}
        owner = self.f.owner_record(request, pins, 'native-reference-capture-complete', str(file))
        studio = Path(review.__file__).parent
        owner['args'] = ['/usr/bin/sandbox-exec', '-f', str(studio / 'native_localhost_only.sb'), str(self.f.node),
                         str(studio / 'native_short_capture.mjs'), str(request_file)]
        write_json(root / 'capture.render.json', owner); seal_capture(root, self.render)

    def finalize(self, root: Path, request: dict) -> None:
        """Model the existing completed final owner, without launching any worker."""
        file = root / 'export-request.json'; pins = {**request['pins'], str(file): digest(file)}
        checks = root / 'checks.json'; status = 'native-short-checked-for-review'
        write_json(checks, {'status': 'checks-passed-awaiting-owned-cleanup', 'sha256': digest(root / 'review.mp4'),
                           'fullAudioVideoDecodePassed': True, 'pictureFramesChecked': 2})
        owner_file = root / 'verification.render.json'
        write_json(owner_file, self.f.owner_record(request, pins, status, str(checks)))
        write_json(root / 'delivery.json', {'status': status, 'sha256': digest(root / 'review.mp4'),
            'fullAudioVideoDecodePassed': True, 'output': str(root / 'review.mp4'), 'pictureFramesChecked': 2,
            'stages': [{'phase': 'verification', 'receipt': str(owner_file), 'sha256': digest(owner_file), 'status': status}]})

    def test_original_and_resumed_checked_exports_admit(self) -> None:
        """Original and resumed checked exports admit."""
        row = {'id': 'DistinctName', 'title': 'Distinct title', 'export': str(self.f.root)}
        admitted = review.read_composition(row)
        self.assertEqual(admitted.video_sha256, digest(self.f.root / 'review.mp4'))
        target = self.f.base / 'resumed'; request = prepare_reverification(self.f.current(target), self.render)
        target.mkdir(); self.f.write_request(request)
        copy_picture(self.f.root / 'review.mp4', target / 'review.mp4', admitted.video_sha256)
        copy_picture(self.f.root / 'native-frames.json', target / 'native-frames.json', digest(self.f.root / 'native-frames.json'))
        self.finalize(target, request)
        second = review.read_composition({**row, 'export': str(target)})
        self.assertEqual(second.video_sha256, admitted.video_sha256)

    def test_changed_or_failed_final_owner_and_checks_reject(self) -> None:
        """Changed or failed final owner and checks reject."""
        file = self.f.root / 'checks.json'; original = file.read_bytes()
        write_json(file, {'status': 'failed'})
        with self.assertRaises(ValueError): review.checked_delivery(self.f.root)
        file.write_bytes(original)
        owner = self.f.root / 'verification.render.json'; data = json.loads(owner.read_text()); data['cleanup']['verified'] = False
        write_json(owner, data)
        with self.assertRaises((ValueError, RuntimeError)): review.checked_delivery(self.f.root)

    def test_missing_or_changed_jpeg_and_project_reject(self) -> None:
        """Missing or changed jpeg and project reject."""
        image = self.f.root / 'pose-0.jpg'; image.write_bytes(b'changed')
        with self.assertRaises((ValueError, RuntimeError)): review.checked_delivery(self.f.root)
        image.write_bytes(b'TEST JPEG bytes')
        (self.f.project / 'index.html').write_text('changed source')
        with self.assertRaises((ValueError, RuntimeError)): review.checked_delivery(self.f.root)

    def test_unknown_long_delivery_status_never_invents_an_adapter(self) -> None:
        """Unknown long delivery status never invents an adapter."""
        file = self.f.root / 'delivery.json'; data = json.loads(file.read_text()); data['status'] = 'native-long-checked-for-review'
        write_json(file, data)
        with self.assertRaisesRegex(ValueError, 'unchecked'): review.checked_delivery(self.f.root)


if __name__ == '__main__': unittest.main()
