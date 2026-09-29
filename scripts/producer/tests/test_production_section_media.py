"""Real stage-seal revalidation of synthetic section media; no codec or editorial claims."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_long_sections_acceptance_fixture import LongSectionsFixture
from cross_runtime_canonical_json import canonical_compact_json
from studio.native_short_pipeline import NativeShortPipeline
from studio.production.section_media import read_media_manifest


def pin(file: Path) -> dict:
    """Freeze exact test bytes in the common receipt format."""
    raw = file.read_bytes()
    return {'path': str(file), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


class SectionMediaTests(unittest.TestCase):
    """Use existing StageEvidence and window readers with isolated fake native execution."""

    def setUp(self) -> None:
        """Seal three synthetic windows through the real production owner adapter."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.fixture = LongSectionsFixture(self.base)
        self.enterContext(patch('studio.native_short_pipeline.NativeRun', side_effect=self.fixture.owner_factory))
        parent = NativeShortPipeline(self.fixture.request, {})
        for index in range(3):
            self.fixture.launch_section(parent, f'segment-picture-{index}')
        self.binding = {'sectionId': 'logical-A', 'generation': 1, 'inputIdentity': 'a' * 64, 'frameRange': [0, 75]}
        self.index = {'schemaVersion': 1, 'kind': 'native-long-section-media', **self.binding,
                      'request': pin(self.fixture.root / 'export-request.json'),
                      'planIdentity': self.fixture.request['revision']['identity'], 'windows': []}
        for index in range(3):
            phase = f'segment-picture-{index}'
            value = json.loads((self.fixture.root / f'{phase}.json').read_bytes())
            self.index['windows'].append({'phase': phase,
                'seal': pin(self.fixture.root / f'{phase}-stage.json'),
                'picture': pin(Path(value['piece']['path'])), 'audio': pin(Path(value['audio']['path'])),
                'frameRange': [index * 25, (index + 1) * 25]})

    def publish(self, index: dict | None = None) -> dict:
        """Create only an index; its child media authority always comes from existing seals."""
        file = self.base / 'TEST-media-manifest.json'
        file.write_bytes((canonical_compact_json(self.index if index is None else index) + '\n').encode())
        return {**self.binding, 'mediaManifest': pin(file)}

    def test_existing_seals_prove_six_exact_tiled_observation_bindings(self) -> None:
        """A logical task can index multiple encoded windows without a new picture render."""
        observations = read_media_manifest(self.publish())
        self.assertEqual(len(observations), 6)
        self.assertEqual([row['frameRange'] for row in observations[::2]], [[0, 25], [25, 50], [50, 75]])

    def test_missing_duplicate_or_reordered_window_refused(self) -> None:
        """A valid digest cannot hide gaps, overlapping frames or wrong order."""
        rows = self.index['windows']
        for windows in (rows[:2], [rows[0], rows[0], rows[2]], list(reversed(rows))):
            with self.subTest(windows=windows), self.assertRaisesRegex(ValueError, 'cover|overlap|omit'):
                read_media_manifest(self.publish({**self.index, 'windows': windows}))

    def test_fresh_manifest_cannot_bless_tampered_media_or_seal(self) -> None:
        """Rehashing the aggregate does not supersede a supervised child seal."""
        for key in ('picture', 'audio', 'seal'):
            original = copy.deepcopy(self.index)
            path = Path(self.index['windows'][0][key]['path'])
            raw = path.read_bytes()
            try:
                path.write_bytes(raw + b'corrupt')
                self.index['windows'][0][key] = pin(path)
                with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                    read_media_manifest(self.publish())
            finally:
                path.write_bytes(raw)
                self.index = original

    def test_unknown_generation_foreign_seal_and_range_forgery_refused(self) -> None:
        """Both logical scope and the exact window boundary are independently checked."""
        changed = copy.deepcopy(self.index)
        changed['windows'][0]['seal'] = changed['windows'][1]['seal']
        bad_range = copy.deepcopy(self.index)
        bad_range['windows'][0]['frameRange'] = [False, 25]
        for index in ({**self.index, 'generation': 2}, {**self.index, 'generation': True}, changed, bad_range):
            with self.subTest(index=index), self.assertRaises(ValueError):
                read_media_manifest(self.publish(index))

    def test_request_mutation_or_linked_manifest_refused(self) -> None:
        """An index pins the published request and cannot redirect through a link."""
        binding = self.publish()
        path = Path(binding['mediaManifest']['path'])
        original = path.with_suffix('.original')
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaises((ValueError, RuntimeError)):
            read_media_manifest(binding)
        path.unlink()
        original.rename(path)
        request = self.fixture.root / 'export-request.json'
        request.write_bytes(request.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'artifact bytes changed'):
            read_media_manifest(binding)


if __name__ == '__main__':
    unittest.main()
