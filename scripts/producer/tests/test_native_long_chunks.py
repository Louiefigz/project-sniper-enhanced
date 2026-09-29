"""Long-only candidate geometry; these tests grant no media or editorial approval."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import tempfile
import unittest
from pathlib import Path

from _native_long_isolation_fixture import write_static_project
from graphics.graphics_render import GSAP_CORE
from studio.native_region_contract import derive_region_map
from studio.native_region_motion import VERSION, motion_markup
from studio.native_region_runtime import GSAP_ASSET
from studio.native_segments.long_chunks import assignment_chunk_map, derive_long_chunks
from studio.native_segments.long_plan import identity, initial_long_plan, repair_long_plan


class LongChunkPlanningTests(unittest.TestCase):
    """Exercise actual scene files, cold region readers and bounded encoder mapping."""

    def setUp(self) -> None:
        """Keep candidate geometry and all runtime files within an isolated fixture."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.canvas = {'width': 320, 'height': 180, 'totalFrames': 15000, 'frameRate': '25/1'}
        self.project = write_static_project(self.root / 'project', self.canvas, ('A', 'B'))
        self.assignments = [{'sectionId': 'A', 'frameRange': [0, 7500]},
                            {'sectionId': 'B', 'frameRange': [7500, 15000]}]
        self.revision = initial_long_plan(self.canvas, 'a' * 64)
        self.scenes(list(range(0, 15001, 1500)))

    def scenes(self, edges: list[int]) -> None:
        """Write explicit authored scene geometry without inventing editorial reviews."""
        value = {'canvas': self.canvas, 'scenes': [{'startFrame': start, 'endFrame': end,
                 'mediaIds': []} for start, end in zip(edges, edges[1:])]}
        (self.project / 'LONG-PROJECT.json').write_text(json.dumps(value))

    def derive(self) -> dict:
        """Invoke the real Long-only planning reader against current fixture bytes."""
        return derive_long_chunks(self.project, self.assignments, self.revision)

    def motion(self, start: int, end: int) -> None:
        """Stage an actual closed compiler declaration on the first creative host."""
        runtime = self.project / GSAP_ASSET
        runtime.parent.mkdir(parents=True)
        runtime.write_text(Path(GSAP_CORE).read_text().replace('</script', '<\\/script'))
        root = self.project / 'index.html'
        root.write_text(root.read_text().replace('</body>', f'<script src="{GSAP_ASSET}"></script></body>'))
        file = self.project / 'compositions/unit-0.html'
        value = {'schemaVersion': 1, 'rule': VERSION, 'compositionId': 'unit-0',
                 'frameRate': '25/1', 'totalFrames': 7500, 'tweens': [{'target': 'title',
                 'startFrame': start, 'endFrame': end, 'from': {'x': 0}, 'to': {'x': 25}, 'ease': 'none'}]}
        file.write_text(file.read_text().replace('<p>', '<p data-motion-id="title">')
                        .replace('</template>', motion_markup(value) + '</template>'))
        (self.project / 'REVIEW-REGIONS.json').write_text(json.dumps(derive_region_map(self.project, self.canvas)))

    def test_ten_chunks_retain_two_creative_owners_and_exact_encoder_coverage(self) -> None:
        """Many chunks create neither tasks nor overlapping final picture ownership."""
        original = copy.deepcopy(self.revision)
        result = self.derive()
        self.assertEqual(len(result['chunks']), 10)
        self.assertEqual({row['sectionId'] for row in result['chunks']}, {'A', 'B'})
        self.assertEqual([index for row in result['chunks'] for index in row['windowIndexes']],
                         list(range(len(result['encoderBoundaries']) - 1)))
        self.assertEqual(result, self.derive())
        self.assertEqual(original, self.revision)
        self.assertTrue(result['pending'])

    def test_non_grid_scene_edges_split_only_proposed_windows(self) -> None:
        """A real scene edge need not coincide with the existing 250-frame encoder grid."""
        self.scenes([0, 1525, 3100, 4500, 6000, 7500, 9000, 10500, 12000, 13500, 15000])
        result = self.derive()
        self.assertEqual(result['chunks'][0]['frameRange'], [0, 1525])
        self.assertIn(1525, result['encoderBoundaries'])
        self.assertNotIn(1525, [row['startFrame'] for row in self.revision['renderWindows']])
        self.assertLessEqual(max(end - start for start, end in zip(result['encoderBoundaries'],
                                                                 result['encoderBoundaries'][1:])), 250)

    def test_no_scene_edge_does_not_create_sixty_second_cut(self) -> None:
        """An exception remains whole when no earlier authored scene boundary exists."""
        self.scenes([0, 7500, 15000])
        result = self.derive()
        self.assertEqual([row['frameRange'] for row in result['chunks']], [[0, 7500], [7500, 15000]])
        self.assertTrue(all(row['durationException'] for row in result['chunks']))

    def test_motion_crossing_preferred_edge_moves_chunk_without_changing_motion(self) -> None:
        """Protect actual 55–65-second motion even when the next scene edge exceeds90 seconds."""
        self.motion(1375, 1625)
        result = self.derive()
        self.assertEqual(result['chunks'][0]['frameRange'], [0, 3000])
        self.assertTrue(result['chunks'][0]['durationException'])
        self.assertEqual(result['evidence']['motionSpans'][0]['frameRange'], [1375, 1625])

    def test_stale_region_or_unknown_motion_never_becomes_candidate_authority(self) -> None:
        """A modified actual source is checked by the existing cold isolation reader."""
        file = self.project / 'compositions/unit-0.html'
        file.write_text(file.read_text().replace('</template>', '<script>bad()</script></template>'))
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.derive()

    def test_motion_across_creative_boundary_requires_shared_transition_contract(self) -> None:
        """An existing creative edge cannot assign overlapping motion to two workers."""
        self.motion(4900, 5100)
        self.assignments[0]['frameRange'][1] = 5000
        self.assignments[1]['frameRange'][0] = 5000
        with self.assertRaisesRegex(ValueError, 'shared transition contract'):
            self.derive()

    def test_added_chunk_edges_cannot_raise_existing_encoder_owner_limit(self) -> None:
        """Natural edge selection stays inside the same768-window admission ceiling."""
        self.revision = initial_long_plan(self.canvas, 'a' * 64,
                                          [*range(0, 15000, 20), 15000])
        self.scenes([*range(0, 15000, 1501), 15000])
        self.assertLessEqual(len(self.derive()['encoderBoundaries']) - 1, 768)
        # A valid existing grid at its limit leaves no room for additional scene cuts.
        edges = sorted({*range(0, 15001, 20), *range(1, 19)})
        self.revision = initial_long_plan(self.canvas, 'a' * 64, edges)
        with self.assertRaisesRegex(ValueError, 'boundaries'):
            self.derive()

    def test_short_and_noncovering_creative_ranges_are_refused(self) -> None:
        """No Short default or guessed ownership enters the Long helper."""
        (self.project / 'SHORT-PROJECT.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Long only'):
            self.derive()
        (self.project / 'SHORT-PROJECT.json').unlink()
        self.assignments[1]['frameRange'][0] += 1
        with self.assertRaisesRegex(ValueError, 'exact clock'):
            self.derive()

    def test_rational_clock_uses_frames_without_rounding_chunk_endpoints(self) -> None:
        """Fractional FPS preferences do not rescale or round authored scene boundaries."""
        self.canvas['frameRate'] = '30000/1001'
        self.canvas['totalFrames'] = 60000
        self.project = write_static_project(self.root / 'rational', self.canvas, ('A', 'B'))
        self.assignments = [{'sectionId': 'A', 'frameRange': [0, 30000]},
                            {'sectionId': 'B', 'frameRange': [30000, 60000]}]
        self.revision = initial_long_plan(self.canvas, 'a' * 64)
        self.scenes([*range(0, 60000, 1800), 60000])
        result = self.derive()
        self.assertEqual(result['chunks'][0]['frameRange'], [0, 1800])
        self.assertEqual(result['encoderBoundaries'][-1], 60000)

    def test_assignment_map_does_not_inherit_sibling_geometry_or_source_digest(self) -> None:
        """A changed B scene cannot change A's frozen review geometry fingerprint."""
        before = assignment_chunk_map(self.derive(), 'A')
        self.scenes([*range(0, 9000, 1500), 9025, 10500, 12000, 13500, 15000])
        after = assignment_chunk_map(self.derive(), 'A')
        self.assertEqual(before, after)
        self.assertEqual(before['chunks'][0]['windowRanges'][0], [0, 250])

    def test_local_repair_preserves_geometry_and_unaffected_encoder_identities(self) -> None:
        """Planning geometry is separate from existing exact per-window repair versions."""
        result = self.derive()
        changes = {'pictureInputs': 'b' * 64, 'global': False, 'ranges': [[3200, 3250]],
                   'files': [], 'reasons': ['test local change']}
        repaired = repair_long_plan(self.revision, changes, self.canvas)
        self.assertEqual(derive_long_chunks(self.project, self.assignments, repaired), result)
        self.assertEqual(repaired['renderWindows'][0], self.revision['renderWindows'][0])
        self.assertEqual(repaired['repair']['affectedSections'], [12])

    def test_rehashed_window_gap_or_overlap_is_not_silently_repaired_by_mapping(self) -> None:
        """Grid and identity agreement cannot excuse missing or duplicated encoded frames."""
        for end in (100, 300):
            revision = copy.deepcopy(self.revision)
            revision['renderWindows'][0]['endFrame'] = end
            revision['grid']['gops'][0][1] = end
            revision['identity'] = identity({key: value for key, value in revision.items() if key != 'identity'})
            with self.subTest(end=end), self.assertRaisesRegex(ValueError, 'gap or overlap'):
                derive_long_chunks(self.project, self.assignments, revision)


if __name__ == '__main__':
    unittest.main()
