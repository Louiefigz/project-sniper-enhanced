"""Bounded review package geometry, durable membership and retained failed artifacts."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from test_native_long_chunk_admission import ChunkAdmissionTests
from cut_preview_io import write_new
from studio.native_budget_registry import BudgetRefused
from studio.native_long_chunk_evidence import transition_evidence
from studio.native_long_chunks import bind_chunk_request
from studio.native_segments.review_budget import previous_owner
from studio.native_segments.review_package import retain_partial_receipt
from studio.native_segments.review_scopes import edge_windows, package_scopes, phase_for, phase_scope


class ReviewScopeTests(ChunkAdmissionTests):
    """Reuse real cold authored contracts; inherited admission checks remain meaningful."""

    def test_long_transition_entrance_and_settled_context_are_included(self) -> None:
        """A legal transition wider than two encoder windows cannot lose its context."""
        transition = self.value['transitions'][0]
        transition['frameRange'] = [1000, 2000]
        transition.update(transition_evidence(self.project, self.geometry, transition['frameRange']))
        self.publish()
        request = bind_chunk_request(self.request())
        windows = edge_windows(request, 1500)
        self.assertEqual([windows[0]['startFrame'], windows[-1]['endFrame']], [750, 2250])
        scope = next(row for row in package_scopes(request) if row['kind'] == 'neighboring-edge')
        self.assertEqual(scope['frameRange'], [750, 2250])
        self.assertEqual(phase_scope(request, phase_for(scope['id'])), scope)

    def test_global_join_uses_full_expanded_range(self) -> None:
        """Creative joins retain the last expanded window, not only the second window."""
        request = bind_chunk_request(self.request())
        scope = next(row for row in package_scopes(request) if row['kind'] == 'global-neighboring-edge')
        self.assertEqual(scope['frameRange'], [7000, 8000])
        self.assertEqual(len(scope['windows']), 4)
        with self.assertRaisesRegex(ValueError, 'outside'):
            phase_scope(request, phase_for('invented-scope'))

    def test_cold_inventory_forecasts_packages_and_refuses_owner_overflow(self) -> None:
        """New derived work gets bounded before launch; no historical capacity is increased."""
        from studio.native_segments.review_forecast import package_seconds, project_work, require_owner_room
        from studio.native_budget_section_schema import MAX_SECTION_OWNERS
        from studio.production.formats import LONG_POLICY
        work = project_work(self.project, self.context)
        self.assertEqual(len(work['scopes']), 19)
        self.assertGreater(sum(work['seconds'].values()), 600)
        self.assertGreater(package_seconds(work, LONG_POLICY['rates'], '*'), 0)
        settings = {'reviewWork': work, 'previewInventory': [], 'context': self.context}
        require_owner_room({'sectionOwners': []}, settings)
        with self.assertRaisesRegex(BudgetRefused, 'capacity'):
            require_owner_room({'sectionOwners': [{}] * (MAX_SECTION_OWNERS - 1)}, settings)

    def test_pre_reservation_preview_keeps_long_transition_continuous(self) -> None:
        """Protected context remains one clip rather than three disconnected region samples."""
        from studio.native_segments.review_forecast import preview_ranges
        transition = self.value['transitions'][0]
        transition['frameRange'] = [1000, 2000]
        transition.update(transition_evidence(self.project, self.geometry, transition['frameRange']))
        self.publish()
        clips = preview_ranges(self.project, self.context, 'A', [{'startFrame': 0, 'endFrame': 100}])
        covering = [row for row in clips if row['startFrame'] <= 750 and row['endFrame'] >= 2250]
        self.assertEqual(len(covering), 1)
        self.assertGreater(covering[0]['endFrame'] - covering[0]['startFrame'], 25 * 12)


class ReviewMembershipTests(unittest.TestCase):
    """Same-store owner history closes duplicate and generation alias loopholes."""

    def owner(self, token: str = 'a') -> dict:
        """A nonpicture owned member beneath one already-counted family."""
        return {'phase': f'family-{token * 32}-{phase_for("chunk-test")}', 'attemptId': 'c' * 32,
                'inputIdentity': 'd' * 64, 'status': 'running'}

    def test_same_scope_across_invocations_cannot_duplicate_aac(self) -> None:
        """Neither a new invocation token nor altered input identity creates a free member."""
        first, second = self.owner(), self.owner('b')
        with self.assertRaisesRegex(BudgetRefused, 'live owner'):
            previous_owner([first], second)
        first['status'] = 'succeeded'
        with self.assertRaisesRegex(BudgetRefused, 'no second AAC'):
            previous_owner([first], second)
        first['status'] = 'failed'
        self.assertIs(previous_owner([first], second), first)
        second['inputIdentity'] = 'e' * 64
        with self.assertRaisesRegex(BudgetRefused, 'changed'):
            previous_owner([first], second)

    def test_new_counted_family_has_distinct_package_membership(self) -> None:
        """A separately authorized repair family may package its new media generation."""
        first, second = self.owner(), self.owner('b')
        first['status'] = 'succeeded'
        second['attemptId'] = 'f' * 32
        self.assertIsNone(previous_owner([first], second))

    def test_retry_retains_partial_candidate_and_never_moves_completed_seal(self) -> None:
        """Failed output is retained, so -n can safely create the authorized retry candidate."""
        import tempfile
        from pathlib import Path
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        phase = phase_for('chunk-test')
        file = root / f'{phase}.json'
        write_new(file, {'failed': 'TEST candidate'})
        write_new(root / f'{phase}.render.json', {'completedAt': 'TEST', 'status': 'failed'})
        retain_partial_receipt(root, phase)
        self.assertFalse(file.exists())
        self.assertEqual(len(list(root.glob(f'{phase}-unsealed-*.json'))), 1)
        write_new(file, {'complete': 'TEST candidate'})
        write_new(root / f'{phase}-stage.json', {'seal': 'TEST'})
        with self.assertRaisesRegex(ValueError, 'sealed package'):
            retain_partial_receipt(root, phase)
        self.assertTrue(file.exists())


class ReviewAdmissionClockTests(unittest.TestCase):
    """Actual durable admission refuses when cold owner observation consumes remaining time."""

    def test_actual_owner_proof_expiry_never_records_launch_charge(self) -> None:
        """A fresh clock is taken after process/family proof, before the pure final debit."""
        from _native_section_budget_fixture import SectionBudgetFixture
        from studio import native_budget_sections as sections
        from studio.native_budget_clock import BudgetExhausted
        fixture = SectionBudgetFixture(self)
        observe = sections.reconcile_owners

        def expire(rows: list[dict], elapsed: float) -> None:
            """Perform the real observation, then cross the original clock while proof was read."""
            observe(rows, elapsed)
            fixture.elapsed = 9001

        with patch.object(sections, 'reconcile_owners', side_effect=expire):
            with self.assertRaises(BudgetExhausted):
                sections.SectionBudgetOwner(fixture.request, 'segment-picture-0').before_launch()
        clip = fixture.record()['clips']['A']
        self.assertEqual(clip.get('sectionOwners'), [])
        self.assertEqual(clip['counters']['pictureGeneration'], 0)
        self.assertEqual(fixture.record()['clock']['elapsed'], 9001)
