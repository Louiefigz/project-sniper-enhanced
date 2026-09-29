"""Current material approval propagates through completed section-task dependencies."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest

from studio.production.section_results import read_completed_result
import test_production_section_results as result_fixture


class SectionApprovalTests(unittest.TestCase):
    """Revalidate the existing approval DAG without changing persisted completion flags."""

    def setUp(self) -> None:
        """Build a valid completed author and reviewer before approval changes."""
        self.fixture = result_fixture.SectionResultTests('test_author_and_both_review_roles_revalidate_completed_bytes')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.before = {'identity': 'before', 'script': 'a' * 64, 'title': 'Original title'}
        self.rows = self.fixture.record['clips']['long']['approvals']
        self.rows.append(self.before)
        self.fixture.author['claim']['approval'] = 'before'
        self.review = self.fixture.task('early-review', 'early-review')
        self.fixture.finish(self.review, self.fixture.result(self.review))

    def read(self) -> dict:
        """Use the actual assembly reader for the registered reviewer chain."""
        return read_completed_result(self.fixture.record, self.review['id'], self.review['sectionBinding'])

    def test_changed_script_blocks_completed_chain_without_stored_stale_flag(self) -> None:
        """Both author and reviewer remain completed, but their approval cannot be reused."""
        self.rows.append({**self.before, 'identity': 'after', 'script': 'b' * 64})
        self.assertFalse(self.fixture.author['approvalStale'])
        self.assertFalse(self.review['approvalStale'])
        with self.assertRaisesRegex(ValueError, 'dependency approval'):
            self.read()

    def test_changed_title_blocks_completed_chain(self) -> None:
        """Materially different titles invalidate dependent judgments too."""
        self.rows.append({**self.before, 'identity': 'after', 'title': 'Entirely different promise'})
        with self.assertRaisesRegex(ValueError, 'dependency approval'):
            self.read()

    def test_unchanged_script_and_normalized_title_remain_current(self) -> None:
        """The existing approval equivalence rules are reused, not replaced by identity-only checks."""
        self.rows.append({**self.before, 'identity': 'after', 'title': ' Original title '})
        self.assertEqual(self.read()['review']['status'], 'pass')

    def test_return_to_original_approval_restores_dynamic_currentness(self) -> None:
        """Dynamic revalidation follows actual current approval, rather than sticky inferred status."""
        self.rows.append({**self.before, 'identity': 'after', 'script': 'b' * 64})
        with self.assertRaisesRegex(ValueError, 'dependency approval'):
            self.read()
        self.rows.append(dict(self.before))
        self.assertEqual(self.read()['review']['status'], 'pass')

