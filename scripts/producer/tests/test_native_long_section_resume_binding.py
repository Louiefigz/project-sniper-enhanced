"""Public section-resume policy and multihop saved-window regression tests.

Native execution and recorded judgments are synthetic; request/history and donor
bindings exercise actual production readers. These are not editorial approvals.
"""
from __future__ import annotations

import tempfile
import unittest
import shutil
import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from _native_long_sections_acceptance_fixture import LongSectionsFixture
from studio.native_export_history import (
    register_attempt, require_current_section_attempt, section_attempt_sequence,
)
from studio.native_long_export import select_and_publish
from studio.native_runtime import digest
from studio.native_segments import owners, supervision
from studio.native_short_pipeline import NativeShortPipeline, NativeStageFailure


class SectionResumeBindingTests(unittest.TestCase):
    """Keep preview admission and all sealed-window ancestry through explicit resume."""

    def setUp(self) -> None:
        """Use an isolated registered request with a synthetic admitted preview policy."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch('studio.native_export_history.history_directory',
                                return_value=self.base / 'history'))
        for module in ('native_budget_exporter', 'native_budget_binding'):
            self.enterContext(patch(f'studio.{module}.default_root', return_value=self.base / 'private-budgets'))
        self.fixture = LongSectionsFixture(self.base)
        self.preview = self.base / 'TEST-preview-reviews.json'
        self.preview.write_text('{"TEST":"synthetic review; no real approval"}')
        self.fixture.request.update(previewOnly=False, previewReviews=str(self.preview))
        self.fixture.request['pins'][str(self.preview)] = digest(self.preview)
        self.fixture.write_request(self.fixture.request)
        register_attempt(self.fixture.request)
        self.enterContext(patch('studio.native_short_pipeline.NativeRun',
                                side_effect=self.fixture.owner_factory))
        self.enterContext(patch.object(supervision, 'section_capacity', return_value=1))
        self.enterContext(patch.object(supervision.SectionProcesses, 'launch', autospec=True,
                                      side_effect=lambda process, phase:
                                      self.fixture.launch_section(process.pipeline, phase)))

    def test_public_explicit_resume_keeps_final_preview_policy(self) -> None:
        """A saved final-section request must not silently become a preview-only request."""
        request = {**self.fixture.request, 'output': str(self.base / 'public-resume'),
                   'pins': dict(self.fixture.inputs)}
        request.pop('previewReviews')
        request.pop('previewOnly')
        args = Namespace(resume_from=self.fixture.root, prepared_master=None, audio_donor=None,
                         preview_only=False, preview_reviews=None, preview_from=None, section_reviews=None)
        self.enterContext(patch('studio.native_motion_previews.discover_preview', return_value=None))
        self.enterContext(patch('studio.native_preview_recovery.bind_section_recovery', side_effect=lambda row: row))
        self.enterContext(patch('studio.native_motion_review.review_input_pins',
                                return_value={str(self.preview): digest(self.preview)}))
        self.enterContext(patch('studio.native_source_store.hold_source_store_owner', return_value='TEST-owner'))
        # This legacy synthetic fixture tests preview binding, not live budget admission.
        self.enterContext(patch('studio.native_budget_exporter.resolve_binding', return_value=None))
        result = select_and_publish(args, request)
        self.assertFalse(result['previewOnly'])
        self.assertEqual(result['previewReviews'], str(self.preview))
        self.assertEqual(result['sectionAttemptSequence'], 2)

    def test_explicit_resume_of_restored_attempt_keeps_all_original_donors(self) -> None:
        """Repeated resume must traverse seals referenced by a previous restored attempt."""
        self.fixture.failures['segment-picture-2'] = True
        with self.assertRaises(NativeStageFailure):
            owners.run_revision_windows(NativeShortPipeline(self.fixture.request, {}))
        restored = owners.bind_window_recovery(self.fixture.restart(), [self.fixture.root])
        self.fixture.write_request(restored)
        register_attempt(restored)
        self.fixture.failures.clear()
        owners.run_revision_windows(NativeShortPipeline(restored, {}))
        self.assertEqual(len(restored['revision']['windowDonors']), 2)
        next_request = {**self.fixture.request, 'output': str(self.base / 'third'),
                        'pins': dict(self.fixture.inputs), 'sectionAttemptSequence': 3,
                        'revision': dict(self.fixture.request['revision'])}
        selected = owners.bind_window_recovery(next_request, [Path(restored['output'])])
        self.assertEqual(set(selected['revision'].get('windowDonors', {})),
                         {'segment-picture-0', 'segment-picture-1', 'segment-picture-2'})
        Path(selected['output']).mkdir()
        self.fixture.write_request(selected)
        register_attempt(selected)
        self.fixture.calls.clear()
        owners.run_revision_windows(NativeShortPipeline(selected, {}))
        self.assertEqual(self.fixture.calls, [])
        for phase in selected['revision']['windowDonors']:
            self.assertTrue(owners.current_window(selected, phase))

    def test_deleted_newer_output_does_not_restore_old_publication_authority(self) -> None:
        """Artifact cleanup must not roll back immutable launch generations."""
        original = self.fixture.request
        require_current_section_attempt(original)
        newer = self.fixture.restart()
        self.fixture.write_request(newer)
        register_attempt(newer)
        shutil.rmtree(newer['output'])
        self.assertEqual(section_attempt_sequence(original), 3)
        with self.assertRaisesRegex(ValueError, 'superseded'):
            require_current_section_attempt(original)
        rollback = {**original, 'output': str(self.base / 'rollback'), 'sectionAttemptSequence': 2}
        Path(rollback['output']).mkdir()
        self.fixture.write_request(rollback)
        with self.assertRaisesRegex(ValueError, 'duplicate or rolled back'):
            register_attempt(rollback)

    def test_ordinary_revision_identity_is_not_a_section_launch_registration(self) -> None:
        """History may contain older packet-reuse revisions without section sequences."""
        ordinary = {**self.fixture.request, 'output': str(self.base / 'ordinary'),
                    'revision': {'mode': 'picture-reuse', 'identity': 'b' * 64}}
        ordinary.pop('sectionAttemptSequence')
        Path(ordinary['output']).mkdir()
        self.fixture.write_request(ordinary)
        register_attempt(ordinary)
        self.assertEqual(section_attempt_sequence(self.fixture.request), 2)
        require_current_section_attempt(self.fixture.request)

    def test_removed_attempt_still_refuses_malformed_registration_metadata(self) -> None:
        """Durable history cannot quietly coerce malformed or partial generation fields."""
        pointer = next((self.base / 'history').glob('*.json'))
        original = json.loads(pointer.read_text())
        shutil.rmtree(self.fixture.request['output'])
        cases = [{'sectionAttemptSequence': True}, {'sectionAttemptSequence': 0},
                 {'sectionPlanIdentity': None}, {'sectionPlanIdentity': 'not-a-digest'}]
        for change in cases:
            with self.subTest(change=change):
                pointer.write_text(json.dumps({**original, **change}))
                with self.assertRaisesRegex(ValueError, 'invalid section attempt history'):
                    section_attempt_sequence(self.fixture.request)

    def test_retained_registration_cannot_change_its_plan_identity(self) -> None:
        """Valid-looking pointer metadata must still match the retained request bytes."""
        pointer = next((self.base / 'history').glob('*.json'))
        row = json.loads(pointer.read_text())
        pointer.write_text(json.dumps({**row, 'sectionPlanIdentity': 'b' * 64}))
        with self.assertRaisesRegex(ValueError, 'differs from its immutable request'):
            section_attempt_sequence(self.fixture.request)


if __name__ == '__main__':
    unittest.main()
