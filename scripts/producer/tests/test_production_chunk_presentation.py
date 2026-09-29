"""Continuous chunk presentation gates over real seals with explicitly fictional media."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest

import test_production_chunk_dispatch as fixtures
from cut_preview_io import write_new
from studio.native_segments.review_package import read_package
from studio.native_segments.review_scopes import phase_for
from studio.production.section_chunk_plan import scope_observations
from studio.production.section_media import read_index, read_media_manifest
from studio.production.section_plan import pin_file
from studio.production.section_review_scope import early_join
from studio.production.sections import encoded_spec, materialize_section_reviews


class ChunkPresentationTests(unittest.TestCase):
    """A reviewer receives a muxed clip only after its owned current scope is complete."""

    def setUp(self) -> None:
        """Use actual authored contracts, source closures, task claims and package StageEvidence."""
        self.case = fixtures.ChunkDispatchTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.host = self.case.host

    def first(self) -> dict:
        """Seal one chunk while leaving its neighboring future windows absent."""
        self.host.seal(0)
        return materialize_section_reviews(self.host.request, 'encoded')['readyChunks'][0]

    def test_ready_clip_binds_playback_listening_and_underlying_windows(self) -> None:
        """Both actual observations name one continuous clip while the raw evidence stays retained."""
        ready = self.first()
        index = read_index(ready['mediaManifest'])
        self.assertEqual(index['presentation']['scopeId'], ready['scopeId'])
        value = read_package(self.host.request, ready['scopeId'], index['presentation']['receipt'])
        observations = ready['observations']
        self.assertEqual([row['kind'] for row in observations], ['encoded-playback', 'audio-listening'])
        self.assertEqual({row['path'] for row in observations}, {value['media']['path']})
        self.assertTrue(all(row['frameRange'] == [0, 60] for row in observations))
        spec = encoded_spec(self.host.request, self.host.context['assignments'][0], self.host.budget.record())
        raw = read_media_manifest({**spec.section_binding, 'frameRange': ready['frameRange'],
                                   'mediaManifest': ready['mediaManifest']})
        self.assertEqual({row['path'] for row in raw}, {index['windows'][0][key]['path'] for key in ('picture', 'audio')})
        reviewer = self.case.claim(ready['taskId'])
        reviewer.record(reviewer.progress(0))
        self.assertEqual(reviewer.task()['state'], 'running')
        self.assertFalse((self.host.fixture.root / 'segment-picture-1-stage.json').exists())

    def test_sealed_windows_without_owned_package_stay_pending(self) -> None:
        """A standalone candidate file is insufficient to publish reviewer work."""
        ready = self.first()
        (self.host.fixture.root / f"{phase_for(ready['scopeId'])}-stage.json").unlink()
        result = materialize_section_reviews(self.host.request, 'encoded')
        self.assertEqual(result['readyChunks'], [])
        self.assertIn('first', result['pendingSections'])
        self.assertEqual(result['pendingPresentation'], [{'sectionId': 'first', 'scopeId': ready['scopeId'],
                         'frameRange': [0, 60], 'status': 'requires-owned-presentation'}])

    def test_omitting_presentation_cannot_downgrade_admitted_chunk_review(self) -> None:
        """Legacy raw window review remains valid only outside the admitted Long chunk route."""
        ready = self.first()
        value = read_index(ready['mediaManifest'])
        value.pop('presentation')
        file = self.host.fixture.root / 'TEST-omitted-presentation.json'
        write_new(file, value)
        spec = encoded_spec(self.host.request, self.host.context['assignments'][0], self.host.budget.record())
        with self.assertRaisesRegex(ValueError, 'omits its continuous presentation'):
            scope_observations(spec.section_binding, ready['scopeId'], pin_file(file))

    def test_changed_muxed_bytes_fail_even_when_underlying_windows_are_intact(self) -> None:
        """Passing old raw window hashes never grants approval to a changed presentation clip."""
        ready = self.first()
        Path(ready['observations'][0]['path']).write_bytes(b'TEST changed muxed clip')
        with self.assertRaises((ValueError, RuntimeError)):
            materialize_section_reviews(self.host.request, 'encoded')

    def test_other_scope_package_cannot_supply_first_chunk_observations(self) -> None:
        """A real sealed package from the next chunk cannot be relabeled as the first scope."""
        ready = self.first()
        self.host.seal(1)
        rows = materialize_section_reviews(self.host.request, 'encoded')['readyChunks']
        other = next(row for row in rows if row['kind'] == 'chunk' and row['scopeId'] != ready['scopeId'])
        value = read_index(ready['mediaManifest'])
        value['presentation']['receipt'] = read_index(other['mediaManifest'])['presentation']['receipt']
        file = self.host.fixture.root / 'TEST-wrong-presentation.json'
        write_new(file, value)
        spec = encoded_spec(self.host.request, self.host.context['assignments'][0], self.host.budget.record())
        with self.assertRaisesRegex(ValueError, 'scope'):
            scope_observations(spec.section_binding, ready['scopeId'], pin_file(file))

    def test_crossing_preview_is_insufficient_for_longer_authored_transition(self) -> None:
        """A frozen short preview cannot silently stand in for the complete transition interval."""
        request = copy.deepcopy(self.host.request)
        left, right = request['sectionProduction']['assignments']
        self.assertTrue(early_join(request, left, right))
        transitions = [item for row in request['sectionChunks']['assignments'] for item in row['transitions']]
        for transition in transitions:
            if transition['frame'] == left['frameRange'][1]:
                transition['frameRange'] = [110, 130]
        with self.assertRaisesRegex(ValueError, 'continuous preview'):
            early_join(request, left, right)


if __name__ == '__main__':
    unittest.main()
