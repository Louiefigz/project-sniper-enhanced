"""Public Long section options retain technical geometry and registered early-review gates."""
from __future__ import annotations

import argparse
import copy
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import native_long_sections as section_cli
import test_production_sections as production_fixture
from cut_preview_io import write_new
from studio import native_long_export as entry
from studio.production import api


class LongSectionEntryTests(unittest.TestCase):
    """Exercise real option wiring with isolated authority and synthetic preview evidence."""

    def setUp(self) -> None:
        """Use the registered production fixture without importing its unittest class twice."""
        self.case = production_fixture.ProductionSectionsTests(
            'test_authors_are_idempotent_and_integrated_outputs_are_required')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.request = self.case.request
        self.canvas = self.request['revision']['canvas']
        self.plan = {'canvas': self.canvas, 'scenes': [
            {'startFrame': 0, 'endFrame': self.canvas['totalFrames']}]}

    def args(self, **changes: object) -> argparse.Namespace:
        """Model parser defaults for only the dependent public section options."""
        return argparse.Namespace(**({'project': self.case.fixture.project, 'sections': False, 'section_plan': None, 'section_reviews': None,
            'resume_from': None, 'repair_from': None, 'preview_only': False} | changes))

    def test_new_plan_splits_technical_windows_at_logical_boundaries(self) -> None:
        """The authored logical assignment must align without the user guessing encoder chunks."""
        args = self.args(section_plan=self.case.planfile)
        request = copy.deepcopy(self.request)
        entry.prepare_sections(args, request, self.plan)
        self.assertEqual([(row['startFrame'], row['endFrame']) for row in request['revision']['renderWindows']],
                         [(0, 50), (50, 75)])
        self.assertEqual(request['revision']['mode'], 'initial-long')

    def test_resume_retains_original_geometry_without_repeat_sections_flag(self) -> None:
        """Previously saved technical windows remain identical instead of being repartitioned."""
        args = self.args(resume_from=self.case.fixture.root)
        self.assertTrue(entry.section_options(args))
        self.assertEqual(entry.section_boundaries(args, self.canvas), [0, 25, 50, 75])
        request = copy.deepcopy(self.request)
        entry.prepare_sections(args, request, self.plan)
        self.assertEqual(request['revision']['grid'], self.request['revision']['grid'])
        self.assertEqual([row['id'] for row in request['revision']['renderWindows']],
                         [row['id'] for row in self.request['revision']['renderWindows']])

    def test_repair_uses_existing_registered_dependency_reader(self) -> None:
        """The public flag delegates its actual closure; it does not construct a second repair planner."""
        args = self.args(repair_from=self.case.fixture.root)
        request = copy.deepcopy(self.request)
        with patch('studio.native_segments.compatibility.prepare_long_repair', return_value={'TEST-repaired': True}) as repair:
            entry.prepare_sections(args, request, self.plan)
        repair.assert_called_once_with(request, self.case.fixture.root)
        self.assertTrue(request['TEST-repaired'])

    def test_shifted_logical_boundary_cannot_relabel_saved_technical_window(self) -> None:
        """A repair cannot silently assign half of an existing window to another task."""
        value = copy.deepcopy(self.case.plan)
        value['assignments'][0]['frameRange'][1] = 49
        value['assignments'][1]['frameRange'][0] = 49
        file = self.case.budget.base / 'shifted.json'
        write_new(file, value)
        with self.assertRaisesRegex(ValueError, 'cannot move logical boundaries'):
            entry.section_boundaries(self.args(section_plan=file, resume_from=self.case.fixture.root), self.canvas)

    def test_canvas_mismatch_refuses_section_plan_before_creation(self) -> None:
        """Partial logical coverage is rejected before launching any media owner."""
        with self.assertRaisesRegex(ValueError, 'cover the current canvas'):
            entry.section_boundaries(self.args(section_plan=self.case.planfile), {**self.canvas, 'totalFrames': 100})

    def test_preview_becomes_final_only_after_registered_current_early_reviews(self) -> None:
        """A flag alone cannot convert preview bytes into final render approval."""
        self.case.bind()
        args = self.args(resume_from=self.case.fixture.root)
        self.request['previewOnly'] = True
        with self.assertRaisesRegex(ValueError, 'unknown section task'):
            entry.bind_task_options(args, self.request)
        self.assertTrue(self.request['previewOnly'])
        self.case.early()
        self.assertFalse(entry.bind_task_options(args, self.request)['previewOnly'])
        record = self.case.budget.record()
        reviewer = next(row for row in record['production']['tasks'].values()
                        if row.get('sectionBinding', {}).get('role') == 'early-review')
        api.supersede_task(self.case.budget.root, 'section-test', reviewer['id'], 'TEST revoke early approval')
        self.request['previewOnly'] = True
        with self.assertRaisesRegex(ValueError, 'not current'):
            entry.bind_task_options(args, self.request)
        self.assertTrue(self.request['previewOnly'])

    def test_explicit_preview_request_preserves_preview_mode_without_early_approval(self) -> None:
        """Preparing new previews remains possible before an independent judgment exists."""
        self.case.bind()
        self.request['previewOnly'] = True
        result = entry.bind_task_options(self.args(resume_from=self.case.fixture.root, preview_only=True), self.request)
        self.assertTrue(result['previewOnly'])

    def test_assignment_binding_is_actual_registered_author_work(self) -> None:
        """The public option goes through production author completion and exact integrated bytes."""
        args = self.args(section_plan=self.case.planfile)
        with self.assertRaisesRegex(ValueError, 'registered claim'):
            entry.bind_task_options(args, self.request)
        self.case.bind()
        self.assertEqual(entry.bind_task_options(args, self.request)['sectionProduction'], self.case.context)

    def test_cli_refuses_repair_and_resume_before_reservation(self) -> None:
        """Conflicting public intentions fail in argparse before budget or output mutation."""
        argv = ['native_long_export.py', '/TEST/project', '/TEST/output',
                '--resume-from', '/TEST/first', '--repair-from', '/TEST/second']
        with patch('sys.argv', argv), patch('studio.native_long_budget.reserve_for_entry') as reserve, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                entry.main()
        self.assertEqual(failure.exception.code, 2)
        reserve.assert_not_called()

    def test_thin_task_cli_calls_existing_authority_without_creating_a_host(self) -> None:
        """Both command modes delegate to the existing task APIs and registered attempt reader."""
        args = section_cli.parser().parse_args(['enqueue', '--plan', str(self.case.planfile)])
        with patch.object(section_cli, 'enqueue_section_authors', return_value={'enqueued': ['author']}) as enqueue:
            self.assertEqual(section_cli.execute(args), {'enqueued': ['author']})
        enqueue.assert_called_once_with(self.case.planfile)
        args = section_cli.parser().parse_args(['reviews', '--attempt', str(self.case.fixture.root), '--stage', 'encoded'])
        with patch.object(section_cli, 'registered_parent', return_value=self.request) as parent, \
                patch.object(section_cli, 'materialize_section_reviews', return_value={'enqueued': ['review']}) as review:
            self.assertEqual(section_cli.execute(args), {'enqueued': ['review']})
        parent.assert_called_once_with(self.case.fixture.root)
        review.assert_called_once_with(self.request, 'encoded')
