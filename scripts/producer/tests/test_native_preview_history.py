"""Synthetic owner receipts test retention integrity, not media or editorial quality."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from studio.native_preview_history import prior_preview, STATUS
from studio.native_motion_review import require_preview_review
from studio.native_runtime import digest


class PreviewHistoryTests(unittest.TestCase):
    """Ancestor loss must invalidate regions even when the latest run rendered no frames."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = str(self.root / 'project')
        self.packet = {'project': self.project, 'canvas': {'frameRate': '30/1', 'totalFrames': 120},
                       'units': [{'id': 'project', 'startFrame': 0, 'endFrame': 120, 'hash': 'a' * 64}]}

    def attempt(self, name: str, prior: Path | None = None) -> Path:
        """Write explicitly fictional owner/media data for the pure receipt reader."""
        root = self.root / name
        root.mkdir()
        file, request_file = root / 'motion-previews.json', root / 'export-request.json'
        request = {'project': self.project, 'output': str(root), 'pins': {}}
        if prior:
            request.update(previewFrom=str(prior), pins={str(prior): digest(prior)})
        request_file.write_text(json.dumps(request))
        owner = {'status': STATUS, 'output': str(file),
                 'exitCode': 0, 'completedAt': 'TEST complete', 'cleanup': {'verified': True, 'survivors': []},
                 'additionalFilePinsBefore': {str(request_file): digest(request_file)}}
        (root / 'preview.render.json').write_text(json.dumps(owner))
        media = root / 'TEST.mp4'
        media.write_bytes(b'TEST receipt reader bytes; not playable media')
        clips = [] if prior else [{'path': str(media), 'sha256': digest(media), 'absoluteFrameRange': [0, 120]}]
        file.write_text(json.dumps({'status': STATUS, 'packet': self.packet, 'clips': clips,
                                   'priorPreview': str(prior) if prior else None}))
        return file

    def test_reused_regions_keep_the_original_media_in_their_chain(self) -> None:
        first = self.attempt('first')
        second = self.attempt('second', first)
        self.assertEqual(prior_preview(second, self.project)['clips'], [])
        (first.parent / 'TEST.mp4').write_bytes(b'TEST replaced ancestor')
        with self.assertRaisesRegex(ValueError, 'media changed'):
            prior_preview(second, self.project)

    def test_rewritten_ancestor_receipt_is_not_new_evidence(self) -> None:
        first = self.attempt('first')
        second = self.attempt('second', first)
        first.write_text(first.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'ancestor changed'):
            prior_preview(second, self.project)

    def test_generated_preview_without_review_cannot_start_full_picture(self) -> None:
        with self.assertRaisesRegex(ValueError, 'independent moving-preview reviews'):
            require_preview_review({'previewOnly': True}, self.packet)

    def test_unverified_cleanup_cannot_be_reused_as_completed_preview(self) -> None:
        first = self.attempt('first')
        file = first.parent / 'preview.render.json'
        owner = json.loads(file.read_text())
        owner['cleanup']['verified'] = False
        file.write_text(json.dumps(owner))
        with self.assertRaisesRegex(ValueError, 'completed shared owner'):
            prior_preview(first, self.project)


if __name__ == '__main__':
    unittest.main()
