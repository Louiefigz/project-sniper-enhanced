"""Public entry validates cheap options and completed early work before spending a launch."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import native_long_budget as entry


class LongBudgetEntryTests(unittest.TestCase):
    """Exercise public reservation dispatch without touching any account authority."""

    def setUp(self) -> None:
        """Keep every public path inside a private temporary root."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        project = self.root / 'project'
        project.mkdir()
        self.args = argparse.Namespace(project=project, output=self.root / 'output',
                                       review_only=False, resume_from=None, repair_from=None)

    def test_review_only_requires_resume_before_reserving(self) -> None:
        """A malformed continuation cannot spend an export attempt."""
        self.args.review_only = True
        with mock.patch.object(entry, 'reserve_long_for_args') as reserve:
            with self.assertRaisesRegex(ValueError, 'explicit resume'):
                entry.reserve_for_entry(self.args)
        reserve.assert_not_called()

    def test_existing_output_fails_before_reserving(self) -> None:
        """Existing evidence paths never become fresh counted work."""
        self.args.output.mkdir()
        with mock.patch.object(entry, 'reserve_long_for_args') as reserve:
            with self.assertRaisesRegex(ValueError, 'new output'):
                entry.reserve_for_entry(self.args)
        reserve.assert_not_called()

    def test_review_only_uses_original_sealed_continuation(self) -> None:
        """The explicit flag selects the same all-section-proof reservation as supplied reviews."""
        self.args.resume_from = self.root / 'prior'
        self.args.review_only = True
        prior = {'revision': {'mode': 'initial-long'}}
        with mock.patch.object(entry, 'registered_parent', return_value=prior), \
                mock.patch.object(entry, 'require_original_authority', return_value={'batchId': 'TEST'}), \
                mock.patch.object(entry, 'reserve_section_review', return_value={'continuationOf': 'TEST'}) as review, \
                mock.patch.object(entry, 'reserve_long_for_args') as reserve:
            self.assertEqual(entry.reserve_for_entry(self.args), (True, {'continuationOf': 'TEST'}))
        review.assert_called_once_with(prior, self.args.project, self.args.output)
        reserve.assert_not_called()

    def test_review_only_cannot_fall_back_to_unbudgeted_render(self) -> None:
        """The explicit no-picture continuation flag requires its durable original authority."""
        self.args.resume_from = self.root / 'prior'
        self.args.review_only = True
        with mock.patch.object(entry, 'registered_parent', return_value={'revision': {'mode': 'initial-long'}}), \
                mock.patch.object(entry, 'require_original_authority', return_value=None), \
                mock.patch.object(entry, 'reserve_long_for_args') as reserve, mock.patch('builtins.print'):
            self.assertEqual(entry.reserve_for_entry(self.args), (False, None))
        reserve.assert_not_called()

    def test_pending_early_review_does_not_consume_final_attempt(self) -> None:
        """An assigned preview needs current completed early judgments before final reservation."""
        self.args.resume_from = self.root / 'prior'
        prior = {'sectionProduction': {'TEST': True}, 'previewOnly': True}
        with mock.patch.object(entry, 'registered_parent', return_value=prior), \
                mock.patch('studio.production.sections.require_all_early_reviews', side_effect=ValueError('pending early')), \
                mock.patch.object(entry, 'reserve_long_for_args') as reserve:
            with self.assertRaisesRegex(ValueError, 'pending early'):
                entry.reserve_for_entry(self.args)
        reserve.assert_not_called()

    def test_explicit_preview_resume_does_not_require_final_early_gate(self) -> None:
        """Preview-only work may be how an early reviewer obtains current evidence."""
        self.args.resume_from = self.root / 'prior'
        self.args.preview_only = True
        with mock.patch('studio.production.sections.require_all_early_reviews') as reviews:
            entry.require_preview_resume_reviews(self.args, {'sectionProduction': {'TEST': True}, 'previewOnly': True})
        reviews.assert_not_called()


if __name__ == '__main__':
    unittest.main()
