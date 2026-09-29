"""Verified clip lineage and cross-revision preview donors; synthetic TEST receipts, no media claims."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import tempfile
import unittest
from pathlib import Path

from _native_short_region_fixture import ShortRegionProject, child_lineage, composition, root_lineage
from studio.native_clip_lineage import lineage_projects, packet_subject, verified_ancestors
from studio.native_preview_history import STATUS, discover_preview, preview_record
from studio.native_review_regions import preview_windows
from studio.native_runtime import digest
from studio.native_short_regions import short_packet


class ClipLineageTests(unittest.TestCase):
    """Only hash-verified same-clip ancestors may donate; another clip never does."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.v1 = ShortRegionProject(self.base / 'native-v1', root_lineage())
        self.v2 = ShortRegionProject(self.base / 'native-v2', child_lineage(self.v1))
        self.v3 = ShortRegionProject(self.base / 'native-v3', child_lineage(self.v2))
        self.other = ShortRegionProject(self.base / 'other-clip', root_lineage('9' * 32))

    def test_chain_subject_and_ancestors(self) -> None:
        self.assertEqual(verified_ancestors(self.v3.directory), [self.v2.directory, self.v1.directory])
        self.assertEqual(lineage_projects(self.v2.directory), [str(self.v2.directory), str(self.v1.directory)])
        self.assertEqual(packet_subject(self.v3.directory), {'clip': 'e' * 32})
        legacy = ShortRegionProject(self.base / 'legacy')
        self.assertEqual(packet_subject(legacy.directory), {'project': str(legacy.directory)})

    def test_changed_parent_is_an_integrity_error_and_removed_parent_ends_the_chain(self) -> None:
        self.v1.plan['strategy']['payoff'] = 'TEST parent rewritten after its child was built'
        self.v1.write()
        with self.assertRaisesRegex(ValueError, 'parent manifest changed'):
            verified_ancestors(self.v2.directory)
        for file in self.v1.directory.rglob('*'):
            if file.is_file():
                file.unlink()
        for folder in sorted(self.v1.directory.rglob('*'), reverse=True):
            folder.rmdir()
        self.v1.directory.rmdir()
        self.assertEqual(verified_ancestors(self.v2.directory), [])

    def test_parent_from_another_clip_is_rejected(self) -> None:
        forged = child_lineage(self.v1)
        manifest = self.other.directory / 'PROJECT-MANIFEST.json'
        forged['parent'].update(path=str(self.other.directory), manifestSha256=digest(manifest),
                                projectHash=json.loads(manifest.read_text())['projectHash'])
        child = ShortRegionProject(self.base / 'forged', forged)
        with self.assertRaisesRegex(ValueError, 'another clip lineage'):
            verified_ancestors(child.directory)


class CrossRevisionPreviewTests(unittest.TestCase):
    """A rebuilt revision discovers its ancestor's preview; unchanged units need no new window."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.v1 = ShortRegionProject(self.base / 'native-v1', root_lineage())
        (self.v1.directory / 'compositions/card-b.html').write_text(composition('card-b', 'color:#fff'))
        self.v2 = ShortRegionProject(self.base / 'native-v2', child_lineage(self.v1))
        (self.v2.directory / 'compositions/card-b.html').write_text(composition('card-b', 'font-size:48px'))
        self.attempts = self.base / 'attempts'
        self.attempts.mkdir()

    def preview(self, project: ShortRegionProject, name: str, prior: Path | None = None) -> Path:
        """Write one completed TEST preview attempt whose clips match the real planner."""
        root = self.attempts / name
        root.mkdir()
        request = {**project.request(), 'output': str(root)}
        packet = short_packet(request)
        previous = json.loads(prior.read_text())['packet'] if prior else None
        clips = []
        for index, window in enumerate(preview_windows(packet, previous)):
            media = root / f'TEST-{index}.mp4'
            media.write_bytes(f'TEST preview clip {index}; not media'.encode())
            clips.append({'path': str(media), 'sha256': digest(media),
                          'absoluteFrameRange': [window['startFrame'], window['endFrame']]})
        if prior:
            request.update(previewFrom=str(prior), pins={**request['pins'], str(prior): digest(prior)})
        file, request_file = root / 'motion-previews.json', root / 'export-request.json'
        request_file.write_text(json.dumps(request))
        (root / 'preview.render.json').write_text(json.dumps({'status': STATUS, 'output': str(file), 'exitCode': 0,
            'completedAt': 'TEST', 'cleanup': {'verified': True, 'survivors': []},
            'additionalFilePinsBefore': {str(request_file): digest(request_file)}}))
        file.write_text(json.dumps({'status': STATUS, 'packet': packet, 'clips': clips,
                                    'priorPreview': str(prior) if prior else None}))
        (root / 'delivery.json').write_text(json.dumps({'status': STATUS, 'completedAt': f'2026-09-27T00:00:0{len(name)}Z'}))
        return file

    def test_revision_reuses_ancestor_preview_and_renders_only_changed_units(self) -> None:
        first = self.preview(self.v1, 'preview-v1')
        request = {**self.v2.request(), 'output': str(self.attempts / 'preview-v2')}
        self.assertEqual(discover_preview(request), first)
        second = self.preview(self.v2, 'preview-v2', first)
        clips = json.loads(second.read_text())['clips']
        self.assertEqual([row['absoluteFrameRange'] for row in clips], [[240, 420]])
        self.assertEqual(preview_record(second, str(self.v2.directory))['clips'], clips)

    def test_another_clip_preview_is_never_a_donor(self) -> None:
        other = ShortRegionProject(self.base / 'other-clip', root_lineage('9' * 32))
        foreign = self.preview(other, 'preview-other')
        request = {**self.v2.request(), 'output': str(self.attempts / 'preview-v2')}
        self.assertIsNone(discover_preview(request))
        with self.assertRaisesRegex(ValueError, 'completed shared owner'):
            preview_record(foreign, str(self.v2.directory))


if __name__ == '__main__':
    unittest.main()
