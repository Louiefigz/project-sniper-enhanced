"""Scoped execution boundaries without granting media or editorial qualification."""
from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from studio.native_long_contract import family_preview_inventory, sample_frame_count
from studio.native_long_scope import request_preview_windows, selected_windows
from studio.native_long_scope_pipeline import execute_scope
from studio.native_visual_plan_application import scoped_allocations
from _native_long_isolation_fixture import write_static_project


class ScopedExecutionTests(unittest.TestCase):
    """Immutable ranges constrain actual dispatch and never authorize a join."""

    def setUp(self) -> None:
        """Use a complete inert static scaffold with real source-derived region declarations."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / 'project'
        self.canvas = {'width': 320, 'height': 180, 'frameRate': '30/1', 'totalFrames': 360}
        write_static_project(self.project, self.canvas, ('ready A', '', ''))
        self.context = {'assignments': [{'sectionId': key, 'frameRange': [index * 120, (index + 1) * 120]}
                                       for index, key in enumerate(('A', 'B', 'C'))]}

    def test_frozen_inventory_declares_all_private_ranges_and_late_joins(self) -> None:
        """Incomplete unrelated author outputs are unnecessary for a bounded whole preview forecast."""
        rows = family_preview_inventory(self.project, self.context)
        self.assertEqual([row['sectionId'] for row in rows], ['A', 'B', 'C', None])
        self.assertEqual(rows[0]['windows'], [[0, 120]])
        self.assertEqual(rows[2]['windows'], [[240, 360]])
        self.assertEqual(rows[3]['windows'], [[59, 301]])
        packet = {'canvas': self.canvas, 'units': []}
        request = {'project': str(self.project), 'sectionProduction': self.context,
                   'productionBudget': {'familyId': 'TEST'}, 'sectionPreviewWindows': rows[-1]['windows']}
        self.assertEqual(request_preview_windows(request, packet), [{'startFrame': 59, 'endFrame': 301}])
        request['sectionPreviewWindows'] = [[0, 1]]
        with self.assertRaisesRegex(ValueError, 'join schedule'):
            request_preview_windows(request, packet)

    def test_only_owned_complete_windows_dispatch(self) -> None:
        """Keep original indices while refusing a logical range cutting through technical ownership."""
        windows = [{'index': index, 'startFrame': index * 120, 'endFrame': (index + 1) * 120}
                   for index in range(3)]
        request = {'revision': {'renderWindows': windows}, 'sectionScope': {'frameRange': [120, 240]}}
        self.assertEqual(selected_windows(request), [windows[1]])
        request['sectionScope']['frameRange'] = [121, 240]
        with self.assertRaisesRegex(ValueError, 'complete technical'):
            selected_windows(request)

    def test_allocated_cross_boundary_visual_is_not_silently_skipped(self) -> None:
        """Every intersecting visual allocation must fit wholly inside the admitted scope."""
        plan = {'allocation': {'decisions': [{'opportunityId': 'A'}, {'opportunityId': 'B'}]},
                'opportunities': [{'id': 'A', 'timing': {'startFrame': 0, 'endFrameExclusive': 120}},
                                  {'id': 'B', 'timing': {'startFrame': 120, 'endFrameExclusive': 240}}]}
        self.assertEqual(scoped_allocations(plan, {'frameRange': [0, 120]}), [{'opportunityId': 'A'}])
        with self.assertRaisesRegex(ValueError, 'cuts through'):
            scoped_allocations(plan, {'frameRange': [0, 121]})

    def test_sample_reservation_matches_owned_seams_and_reverse_visits(self) -> None:
        """No scene-C sample work is charged or dispatched by the A scope."""
        plan = {'canvas': self.canvas, 'scenes': [{'startFrame': index * 120, 'endFrame': (index + 1) * 120}
                                                for index in range(3)]}
        self.assertEqual(sample_frame_count(plan, {'frameRange': [0, 120]}), 12)
        self.assertEqual(sample_frame_count(plan, {'frameRange': [120, 240]}), 12)

    def test_scoped_preview_never_calls_final_pipeline(self) -> None:
        """A preview success records scoped evidence only, with no full-project or delivery claim."""
        root = self.root / 'attempt'
        root.mkdir()
        pipeline = Mock(root=root, request={'sectionScope': {'frameRange': [0, 120]},
                        'productionBudget': {'familyInvocation': 'TEST'}, 'previewOnly': True}, stages=[])
        pipeline.preview.return_value = {'status': 'native-motion-previews-complete'}
        module = 'studio.native_long_scope_pipeline'
        with patch(module + '.require_scope_request'), patch(module + '.complete_scope', return_value=True) as complete:
            self.assertTrue(execute_scope(pipeline))
        pipeline.capture.assert_called_once()
        pipeline.preview.assert_called_once()
        pipeline.render.assert_not_called()
        pipeline.verify.assert_not_called()
        value = complete.call_args.args[1]
        self.assertFalse(value['fullProjectAdmission'])
        self.assertFalse(value['finalAssembly'])


class ScopedOwnerTests(unittest.TestCase):
    """Exercise real immutable section seals with synthetic supervised media owners."""

    def test_a_is_saved_without_dispatching_b_or_c(self) -> None:
        """A valid completed owner is independently readable before later owners exist."""
        from _native_long_sections_acceptance_fixture import LongSectionsFixture
        from studio.native_export_history import register_attempt
        from studio.native_segments import owners, supervision
        from studio.native_short_pipeline import NativeShortPipeline
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch('studio.native_export_history.history_directory', return_value=root / 'history'))
        fixture = LongSectionsFixture(root)
        frame_range = [fixture.request['revision']['renderWindows'][0][key] for key in ('startFrame', 'endFrame')]
        fixture.request['sectionScope'] = {'frameRange': frame_range}
        fixture.write_request(fixture.request)
        register_attempt(fixture.request)
        self.enterContext(patch('studio.native_short_pipeline.NativeRun', side_effect=fixture.owner_factory))
        self.enterContext(patch.object(supervision, 'section_capacity', return_value=2))
        self.enterContext(patch.object(supervision.SectionProcesses, 'launch', autospec=True,
                         side_effect=lambda process, phase: fixture.launch_section(process.pipeline, phase)))
        pipeline = NativeShortPipeline(fixture.request, {})
        supervision.run_sections(pipeline)
        self.assertEqual([label for label, _settings in fixture.calls], ['segment-picture-0'])
        self.assertEqual(owners.current_window(fixture.request, 'segment-picture-0')['window']['index'], 0)
        self.assertFalse((fixture.root / 'segment-picture-1-stage.json').exists())
        self.assertFalse((fixture.root / 'segment-picture-2-stage.json').exists())
        self.assertFalse((fixture.root / 'picture.mp4').exists())


if __name__ == '__main__':
    unittest.main()
