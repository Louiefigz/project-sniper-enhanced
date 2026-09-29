"""Review drafts through the public exporter: distinct seal/status, recovery refusal, promotion.

Media bytes are TEST placeholders and owners are stubbed; seals, readers, request publication
and the real promotion worker run unchanged. Nothing here reviews or approves real media.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_short_draft_fixture import DraftFixture
from _native_short_pipeline_fixture import isolate_early_checks, write_json
from studio.native_runtime import digest
from studio.native_short_autoresume import matching_attempt, recover_automatically
from studio.native_short_draft import DRAFT_LABEL, DRAFT_OUTPUT, DRAFT_STATUS
from studio.native_short_draft_export import prepare_promotion
from studio.native_short_export import execute
from studio.native_short_pipeline import FINAL_STATUS
from studio.native_short_resume import prepare_reverification, render_stage_for_attempt
from studio.native_stage_evidence import read_stage


class ReviewDraftExportTests(unittest.TestCase):
    """A draft is a complete labeled MP4 that no final-media path can launder."""

    def setUp(self) -> None:
        """Private fixture, history and inert tools; only child owners are stubs."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.enterContext(patch('studio.native_export_history.history_directory', return_value=self.base / 'history'))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        isolate_early_checks(self)
        self.use('final-eligible')

    def use(self, state: str) -> None:
        """Select the project's review state as the draft-mode reader would report it."""
        base = self.base / state
        base.mkdir()
        self.f = DraftFixture(base, state)

    def run_export(self, **options: object) -> bool:
        """Drive the actual public execute path with the fixture's tools and stub owners."""
        draft = options.get('review_draft', False)
        values = {'cache': Path(self.f.request['cache']) if draft else None, 'review_draft': False,
                  'promote_draft': None, 'draft_findings': None, 'reference_map': None, **options}
        with patch('studio.native_short_export.local_environment', return_value=(self.f.request['tools'], {})), \
                patch('studio.native_short_export.subprocess.run', side_effect=self.f.admission), \
                patch('studio.native_short_export.install_runtime', return_value=self.f.runtime), \
                patch('studio.native_short_export.input_pins', return_value=dict(self.f.inputs)), \
                patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory):
            return execute(self.f.options(**values))

    def draft(self, name: str = 'draft') -> Path:
        """Publish one complete review draft through the public route."""
        output = self.f.base / name
        self.assertTrue(self.run_export(output=output, review_draft=True))
        return output

    def reviews(self) -> Path:
        """An empty TEST bundle expresses intent only; the real motion gate is stubbed in the worker."""
        file = self.f.base / 'TEST-empty-review-input.json'
        if not file.exists():
            write_json(file, {'schemaVersion': 1, 'reviews': []})
        return file

    def test_review_draft_renders_one_owner_and_publishes_a_distinct_labeled_file(self) -> None:
        """Only the draft owner runs: no capture, previews, preview gate or final verification."""
        output = self.draft()
        self.assertEqual([label for label, _ in self.f.calls], ['draft'])
        self.assertEqual(self.f.calls[0][1].command[-1], 'draft')
        self.assertEqual(self.f.calls[0][1].admission['output'], str(output / DRAFT_OUTPUT))
        request = json.loads((output / 'export-request.json').read_text())
        self.assertTrue(request['reviewDraft'])
        self.assertFalse(request['previewOnly'])
        self.assertNotIn('previewReviews', request)
        delivery = json.loads((output / 'delivery.json').read_text())
        self.assertEqual(delivery['status'], DRAFT_STATUS)
        self.assertEqual((delivery['label'], delivery['editorialReview'], delivery['finalQc']),
                         (DRAFT_LABEL, 'pending', 'not-run'))
        self.assertFalse(delivery['humanApproved'])
        self.assertTrue(delivery['promotable'])
        self.assertEqual(delivery['output'], str(output / DRAFT_OUTPUT))
        self.assertEqual(delivery['sha256'], digest(output / DRAFT_OUTPUT))
        self.assertTrue(any('Final QC not run' in row for row in delivery['limitations']))
        self.assertFalse((output / 'review.mp4').exists())
        self.assertFalse((output / 'render-stage.json').exists())
        record, _pins = read_stage(output / 'draft-stage.json', self.f.inputs, 'draft')
        self.assertEqual(record['artifacts']['draft']['sha256'], delivery['sha256'])

    def test_a_budgeted_draft_charges_its_picture_and_records_its_outcome(self) -> None:
        """The draft's one full picture is pre-charged and its delivery closes the reserved launch."""
        with patch('studio.native_budget_binding.charge_request') as charge, \
                patch('studio.native_budget_owner.record_budget_outcome', return_value=None) as outcome:
            self.draft()
        self.assertEqual([call.args[1] for call in charge.call_args_list], ['pictureGeneration'])
        self.assertEqual(outcome.call_args.args[1]['status'], DRAFT_STATUS)

    def test_draft_built_project_draft_is_labeled_never_promotable(self) -> None:
        """Recorded findings travel into the delivery; promotion is refused before any owner."""
        self.use('draft')
        output = self.draft()
        delivery = json.loads((output / 'delivery.json').read_text())
        self.assertEqual(delivery['projectReviewState'], 'draft')
        self.assertFalse(delivery['promotable'])
        self.assertEqual([row['code'] for row in delivery['openFindings']], ['TEST_OPEN_ISSUE'])
        self.assertTrue(any('never promotable' in row for row in delivery['limitations']))
        self.f.calls.clear()
        with self.assertRaisesRegex(ValueError, 'never be promoted'):
            self.run_export(output=self.f.base / 'promoted', promote_draft=output, preview_reviews=self.reviews())
        self.assertEqual(self.f.calls, [])
        self.assertFalse((self.f.base / 'promoted').exists())

    def test_verify_from_resume_from_and_seal_readers_refuse_a_draft(self) -> None:
        """--verify-from/--resume-from cannot turn draft bytes into a verified final."""
        output = self.draft()
        current = self.f.current(self.f.base / 'verification')
        with self.assertRaisesRegex(ValueError, 'never final media'):
            prepare_reverification(current, output / 'draft-stage.json')
        with self.assertRaisesRegex(ValueError, 'never final media'):
            render_stage_for_attempt(output)
        with self.assertRaisesRegex(ValueError, 'another stage'):
            read_stage(output / 'draft-stage.json', self.f.inputs, 'render')
        with self.assertRaisesRegex(ValueError, 'never final media'):
            self.run_export(output=self.f.base / 'verify', verify_from=output / 'draft-stage.json')
        with self.assertRaisesRegex(ValueError, 'never final media'):
            self.run_export(output=self.f.base / 'resume', resume_from=output)

    def test_automatic_recovery_skips_a_draft_with_identical_inputs(self) -> None:
        """A final export never discovers a completed draft as reusable final media."""
        output = self.draft()
        self.f.terminal()  # The fixture's own unrelated initial attempt ends as a TEST failure.
        # P0 adapt (M-030): the final carries the exporter's own defaults, as the draft does: retained capture (X41) and
        # the content store (native_short_export.py:77-78, 164-167). The fixture's request predates both.
        current = {**self.f.current(self.f.base / 'final'), 'captureMode': 'cached-native-batches',
                   'sourceCacheMode': 'acquire-content-store'}
        request = json.loads((output / 'export-request.json').read_text())
        self.assertEqual([key for key in ('cache', 'captureMode', 'sourceCacheMode', 'audioProfile', 'runtime', 'tools')
                          if request.get(key) != current.get(key)], [])
        self.assertEqual(request['pins'], current['pins'])
        self.assertIsNone(matching_attempt(current, output))
        self.assertEqual(recover_automatically(current)['recoverySelection']['mode'], 'fresh')

    def test_new_attempt_required_and_prior_outputs_stay_immutable(self) -> None:
        """A draft never overwrites an earlier complete MP4 or reuses an attempt directory."""
        first = self.draft('first')
        before = {str(file): digest(file) for file in first.rglob('*') if file.is_file()}
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.run_export(output=first, review_draft=True)
        self.draft('second')
        self.assertEqual(before, {str(file): digest(file) for file in first.rglob('*') if file.is_file()})

    def test_review_bundle_admits_a_sealed_draft_only_as_a_labeled_draft(self) -> None:
        """Bundle admission reads the draft seal; changed bytes are refused, never relabeled."""
        from studio.native_review_contract import read_composition
        output = self.draft()
        row = {'id': 'TestDraft', 'title': 'TEST draft', 'export': str(output)}
        composition = read_composition(row)
        self.assertEqual((composition.review_state, composition.label), ('draft', DRAFT_LABEL))
        self.assertEqual(composition.video, output / DRAFT_OUTPUT)
        (output / DRAFT_OUTPUT).unlink()
        (output / DRAFT_OUTPUT).write_bytes(b'TEST substituted bytes')
        with self.assertRaisesRegex(ValueError, 'incomplete review-draft delivery'):
            read_composition(row)

    def test_promotion_copies_exact_bytes_and_runs_every_final_owner(self) -> None:
        """Editorial gate, capture and verification run; no picture or audio is encoded."""
        draft = self.draft()
        before = {str(file): digest(file) for file in draft.rglob('*') if file.is_file()}
        self.f.calls.clear()
        promoted = self.f.base / 'promoted'
        self.assertTrue(self.run_export(output=promoted, promote_draft=draft, preview_reviews=self.reviews()))
        labels = [label for label, _ in self.f.calls]
        self.assertEqual(labels, ['capture', 'preview-picture-0', 'preview-package-0', 'preview', 'pipeline', 'verification'])
        self.assertEqual(self.f.calls[4][1].command[-1], 'promote')
        self.assertEqual(self.f.promotion_gate_calls, 1)
        delivery = json.loads((promoted / 'delivery.json').read_text())
        self.assertEqual(delivery['status'], FINAL_STATUS)
        self.assertEqual(digest(promoted / 'review.mp4'), digest(draft / DRAFT_OUTPUT))
        self.assertEqual(delivery['promotion']['draftSha256'], digest(draft / DRAFT_OUTPUT))
        self.assertTrue(delivery['promotion']['bytesIdentical'])
        self.assertEqual(delivery['additionalPictureEncodes'], 0)
        self.assertFalse(delivery['humanApproved'])
        record, _pins = read_stage(promoted / 'render-stage.json',
                                   json.loads((promoted / 'export-request.json').read_text())['pins'], 'render')
        self.assertEqual(record['artifacts']['review']['sha256'], delivery['sha256'])
        self.assertEqual(before, {str(file): digest(file) for file in draft.rglob('*') if file.is_file()})

    def test_promotion_refuses_changed_inputs_missing_reviews_and_incomplete_drafts(self) -> None:
        """Different current inputs, no editorial evidence or a failed draft cannot promote."""
        draft = self.draft()
        current = self.f.current(self.f.base / 'promoted')
        changed = {**current, 'pins': {**current['pins'], str(self.f.source): 'a' * 64}}
        with self.assertRaisesRegex(ValueError, 'differ from the sealed draft inputs'):
            prepare_promotion(changed, draft)
        with self.assertRaisesRegex(ValueError, 'preserve the draft attempt'):
            prepare_promotion(self.f.current(draft / 'inside'), draft)
        with self.assertRaisesRegex(ValueError, 'requires current --preview-reviews'):
            self.run_export(output=self.f.base / 'no-reviews', promote_draft=draft)
        delivery = json.loads((draft / 'delivery.json').read_text())
        (draft / 'delivery.json').unlink()
        write_json(draft / 'delivery.json', {**delivery, 'status': 'failed'})
        with self.assertRaisesRegex(ValueError, 'completed promotable review draft'):
            prepare_promotion(current, draft)


if __name__ == '__main__':
    unittest.main()
