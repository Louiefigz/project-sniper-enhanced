"""Initial Long partition and targeted repair regressions; no media approval is fabricated."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.native_segments.dependency import canvas_clock, picture_changes
from studio.native_segments.plan import initial_long_plan, repair_long_plan

CANVAS = {'frameRate': '30000/1001', 'totalFrames': 750, 'width': 1920, 'height': 1080}


def changes(ranges: list, global_change: bool = False) -> dict:
    """An explicit dependency-reader result for test-only immutable projects."""
    return {'pictureInputs': 'b' * 64, 'global': global_change, 'ranges': ranges,
            'files': [], 'reasons': ['test repair']}


class InitialLongSectionPlanTests(unittest.TestCase):
    """Frame bounds and generations preserve only explicitly compatible sections."""

    def setUp(self) -> None:
        """Create a complete initial three-window program."""
        self.plan = initial_long_plan(CANVAS, 'a' * 64)

    def test_initial_has_no_short_ancestor_and_exact_rational_clock(self) -> None:
        """A standalone Long preserves every frame without fabricating a parent."""
        self.assertNotIn('ancestor', self.plan)
        self.assertEqual(self.plan['grid']['gops'], [[0, 250], [250, 500], [500, 750]])
        self.assertEqual((self.plan['grid']['timescale'], self.plan['grid']['tick']), (30000, 1001))
        self.assertEqual(self.plan, initial_long_plan(CANVAS, 'a' * 64))

    def test_local_b_repair_retains_a_c_and_rechecks_both_joins(self) -> None:
        """Current picture versions advance only for the actual dependency closure."""
        repaired = repair_long_plan(self.plan, changes([[310, 350]]), CANVAS)
        before, after = self.plan['renderWindows'], repaired['renderWindows']
        self.assertEqual((before[0], before[2]), (after[0], after[2]))
        self.assertEqual(after[1]['generation'], 2)
        self.assertNotEqual(before[1]['inputIdentity'], after[1]['inputIdentity'])
        self.assertEqual(repaired['repair']['affectedSections'], [1])
        self.assertEqual(repaired['repair']['recheckJoins'], [0, 1])
        self.assertNotEqual(self.plan['identity'], repaired['identity'])

    def test_cross_boundary_change_invalidates_b_and_c(self) -> None:
        """A transition crossing a section boundary cannot be repaired as one side only."""
        repaired = repair_long_plan(self.plan, changes([[490, 510]]), CANVAS)
        self.assertEqual(repaired['repair']['affectedSections'], [1, 2])
        self.assertEqual(repaired['repair']['technicalReuseSections'], [0])

    def test_global_style_change_invalidates_all(self) -> None:
        """Shared dependencies invalidate every picture section."""
        repaired = repair_long_plan(self.plan, changes([[0, 750]], True), CANVAS)
        self.assertEqual(repaired['repair']['affectedSections'], [0, 1, 2])
        self.assertTrue(all(row['generation'] == 2 for row in repaired['renderWindows']))

    def test_audio_only_closure_keeps_picture_identities(self) -> None:
        """An unchanged picture closure does not spend another picture generation."""
        repaired = repair_long_plan(self.plan, changes([]), CANVAS)
        self.assertEqual(repaired['renderWindows'], self.plan['renderWindows'])
        self.assertEqual(repaired['repair']['recheckJoins'], [])

    def test_changed_clock_never_reuses_old_picture_identity(self) -> None:
        """Even same dependency bytes cannot transfer picture between frame clocks."""
        canvas = {**CANVAS, 'frameRate': '30/1'}
        repaired = repair_long_plan(self.plan, {**changes([], True), 'pictureInputs': 'a' * 64}, canvas)
        self.assertNotEqual(repaired['renderWindows'][0]['inputIdentity'],
                            self.plan['renderWindows'][0]['inputIdentity'])

    def test_invalid_partition_and_partial_manifest_are_refused(self) -> None:
        """No gaps, duplicate frame ranges or unbounded owners reach rendering."""
        for bounds in ([0, 251, 500, 750], [0, 250, 250, 750], [1, 250, 500, 750], [0, 250]):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                initial_long_plan(CANVAS, 'a' * 64, bounds)
        broken = copy.deepcopy(self.plan)
        broken['renderWindows'][1]['generation'] += 1
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            repair_long_plan(broken, changes([[300, 350]]), CANVAS)

    def test_repeated_repairs_advance_generation_and_preserve_original(self) -> None:
        """A late original worker cannot present the current B input identity."""
        second = repair_long_plan(self.plan, changes([[300, 350]]), CANVAS)
        third = repair_long_plan(second, changes([[300, 350]]), CANVAS)
        self.assertEqual(third['renderWindows'][1]['generation'], 3)
        self.assertEqual(self.plan['renderWindows'][1]['generation'], 1)
        self.assertEqual(third['renderWindows'][0], self.plan['renderWindows'][0])

    def test_repair_drops_old_operational_donors_before_rebinding(self) -> None:
        """A bound transport donor is not creative plan identity or a replacement donor."""
        previous = {**self.plan, 'windowDonors': {'segment-picture-0': '/TEST/old-stage.json'}}
        repaired = repair_long_plan(previous, changes([[300, 350]]), CANVAS)
        self.assertNotIn('windowDonors', repaired)
        self.assertEqual(repaired['renderWindows'][0], self.plan['renderWindows'][0])


class SectionCapacityTests(unittest.TestCase):
    """Only an exact declared qualification session can test uncommitted capacity."""

    def capacity(self, output: str) -> int:
        """Observe a test-only session through the real workload membership decision."""
        from native_work_qualification import Committed
        from studio.native_segments.supervision import section_capacity
        session = {'value': {'nonce': 'test', 'jobs': [{'project': '/TEST/project', 'attempt': '/TEST/attempt'}]},
                   'slots': {'heavy': 3, 'audio': 1}}
        with patch('studio.native_segments.supervision.host_identity', return_value={}), \
                patch('studio.native_segments.supervision.committed', return_value=Committed()), \
                patch('studio.native_segments.supervision.describe', return_value={}), \
                patch('native_work_pool_state.ledger'), patch('native_work_pool_observe.observe'), \
                patch('native_work_pool_mix.session_of', return_value=session):
            return section_capacity({'project': '/TEST/project', 'output': output})

    def test_qualified_session_matches_exact_export(self) -> None:
        """Declared work may measure three owners before a committed profile exists."""
        self.assertEqual(self.capacity('/TEST/attempt'), 3)

    def test_unrelated_attempt_stays_exclusive(self) -> None:
        """A live session never lends its experimental capacity to unrelated work."""
        self.assertEqual(self.capacity('/TEST/other-attempt'), 1)


class LongDependencyTests(unittest.TestCase):
    """Use the existing DOM closure for Long without requiring a Short ancestor."""

    def project(self, name: str, word: str) -> Path:
        """Write a tiny immutable Long fixture with one timed local title."""
        root = self.root / name
        root.mkdir()
        (root / 'LONG-PROJECT.json').write_text(json.dumps({'canvas': CANVAS}))
        (root / 'index.html').write_text('<html><body><div data-start="10" data-duration="1" '
                                        f'style="position:absolute">{word}</div></body></html>')
        return root

    def setUp(self) -> None:
        """Keep all inputs private to this test."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def test_local_long_title_uses_same_scoped_dom_closure(self) -> None:
        """A timed local title does not invalidate all Long sections."""
        before, after = self.project('old', 'old'), self.project('new', 'new')
        result = picture_changes(before, after)
        self.assertFalse(result['global'])
        self.assertEqual(result['ranges'], [[299, 330]])
        self.assertEqual(canvas_clock(after), ('30000/1001', 750))

    def test_ambiguous_short_and_long_plan_refused(self) -> None:
        """A reader must not guess which timeline owns the section."""
        project = self.project('ambiguous', 'word')
        (project / 'SHORT-PROJECT.json').write_text(json.dumps({'canvas': CANVAS}))
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            canvas_clock(project)


if __name__ == '__main__':
    unittest.main()
