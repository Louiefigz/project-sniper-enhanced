"""Long chunk admission must leave real Short coordination and authority unchanged.

Media owners and Short preflight are inert fixture boundaries. These tests prove
Long-feature isolation and accounting, not actual Short preflight or playback.
The derived case uses the real output authorization and bound recording lineage.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_native_short_pipeline as pipeline_tests
from studio import native_budget_clock as clock
from studio.native_budget_policy import Approval, BatchSpec, new_batch_record, phase_refusal
from studio.native_export import admitted_worker, export_adapter
from studio.native_long_chunks import bind_chunk_request, require_chunk_request
from studio.native_runtime import digest
from studio.production.claims import Enrollment, claim, enroll_director
from studio.production.formats import clip_deadlines
from studio.production.outputs import OutputAuthorization, authorize_output
from studio.production.section_recovery import retain_section_reviews
from studio.production.tasks import TaskSpec, active_ai, enqueue


class ShortChunkIsolationTests(unittest.TestCase):
    """Tripwires detect accidental Long planning in existing Short execution paths."""

    def setUp(self) -> None:
        """Reuse the ordinary Short pipeline's filesystem evidence and inert owners."""
        self.case = pipeline_tests.NativeShortPipelineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fixture = self.case.fixture
        self.fixture.request['adapter'] = 'native-short'
        self.fixture.write_request(self.fixture.request)
        self.early_checks = self.enterContext(patch('studio.native_early_stage.run_early_checks'))
        self.capture_gate = self.enterContext(patch('studio.native_early_stage.capture_diagnostics_gate'))
        self.enterContext(patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1))
        for name in ('studio.native_segments.long_chunks.derive_long_chunks',
                     'studio.production.section_chunk_dispatch.chunk_spec',
                     'studio.production.section_chunk_recovery.retain_chunk_plans'):
            self.enterContext(patch(name, side_effect=AssertionError('Short entered Long chunk path')))

    def test_short_pipeline_keeps_owners_and_no_chunk_metadata(self) -> None:
        """No authored Long contract means no chunk planner, reviewer dispatch or task metadata."""
        request = self.fixture.request
        original = copy.deepcopy(request)
        self.assertEqual(export_adapter(self.fixture.project), 'native-short')
        self.assertIs(bind_chunk_request(request), request)
        require_chunk_request(request)
        self.assertIs(retain_section_reviews(request, original), request)
        self.assertEqual(request, original)
        self.assertTrue(self.case.pipeline().execute(), self.case.delivery())
        self.assertEqual([label for label, _config in self.fixture.calls],
                         ['capture', 'preview-picture-0', 'preview-package-0', 'preview', 'pipeline', 'verification'])
        self.assertEqual(self.case.delivery()['status'], pipeline_tests.FINAL_STATUS)
        self.assertFalse(self.case.delivery()['humanApproved'])
        self.early_checks.assert_called_once()
        self.capture_gate.assert_called_once_with(self.early_checks.call_args.args[0])
        self.assertFalse(self.early_checks.call_args.args[0].is_long)
        self.assertEqual(self.early_checks.call_args.args[0].request['adapter'], 'native-short')
        self.assertNotIn('sectionChunks', self.case.delivery())

    def test_short_reverification_keeps_prior_bytes_without_chunk_recovery(self) -> None:
        """Real sealed Short recovery retains its capture/check-only route and exact prior media."""
        self.case.test_resume_copies_exact_output_and_runs_only_capture_and_verification()
        self.early_checks.assert_not_called()
        self.capture_gate.assert_not_called()

    def test_short_cannot_borrow_a_long_segment_owner(self) -> None:
        """A forged initial-Long revision on a Short still fails the shared owner boundary."""
        request = {**self.fixture.request, 'revision': {'mode': 'initial-long'}}
        settings = SimpleNamespace(command=['segment-picture-0'])
        with self.assertRaisesRegex(ValueError, 'initial Long section plan'):
            admitted_worker(settings, request, self.fixture.root / 'export-request.json')

    def approval(self) -> Approval:
        """Use actual admitted transcript bytes for both standalone and derived Short scripts."""
        transcript = self.fixture.project / 'TEST-transcript.json'
        transcript.write_text(json.dumps({'transcript': [{'words': [{'word': 'TEST', 'start': 0, 'end': 1}]}]}))
        return Approval('TEST Short', 'a' * 64, digest(transcript), 1, str(transcript), 1,
                        ((0, 0),), ('TEST',), ((0.0, 1.0),), 'TEST operator')

    def short_authority(self, derived: bool) -> dict:
        """Authorize real format records without a live account store or media execution."""
        approval = self.approval()
        record = new_batch_record(BatchSpec('short-isolation', ('S',), (), 1, ai_slots=2,
                                            approvals={'S': approval}),
                                  clock.ClockAnchor('TEST-boot', 1000.0, 1800000000.0, 0.0))
        if not derived:
            return record
        authorize_output(record, OutputAuthorization('L', 'long', 'TEST', 'TEST', output_seconds=60), 0)
        record['clips']['L']['output']['lineage'] = {'request': 'b' * 64, 'sources': [approval.source_sha256]}
        authorize_output(record, OutputAuthorization('D', 'short', 'TEST', 'TEST',
                                                      approval=approval, derived_from='L'), 0)
        self.assertEqual(record['clips']['D']['output']['derivedFrom'], 'L')
        return record

    def assert_short_claim(self, derived: bool) -> None:
        """A Short's last-slot claim never waits for unrelated Long authors or extends its clock."""
        record = self.short_authority(derived)
        clip_id = 'D' if derived else 'S'
        host = {'type': 'host', 'host': 'codex', 'thread': 'TEST-director', 'turn': 'TEST-turn'}
        enroll_director(record, Enrollment('director', host, 'v1', 'd' * 64), 0)
        spec = TaskSpec('short-review', record['batchId'], 'review', 'v1', 'e' * 64, 2000,
                        clip_id=clip_id, parent='director')
        specs = (spec,)
        if derived:
            specs += (TaskSpec('long-author', record['batchId'], 'author', 'v1', 'f' * 64, 9000,
                               clip_id='L', parent='director'),)
        enqueue(record, specs, 0)
        before = copy.deepcopy(record['clips'][clip_id]['counters'])
        with patch('studio.production.section_chunk_liveness.read_chunk_plan',
                   side_effect=AssertionError('ordinary Short consulted chunk prerequisites')):
            claim(record, spec.task_id, host, 0)
        task = record['production']['tasks'][spec.task_id]
        self.assertEqual(task['state'], 'claimed')
        self.assertNotIn('sectionBinding', task)
        self.assertEqual(active_ai(record), 2)
        self.assertEqual(record['clips'][clip_id]['counters'], {**before, 'review': before['review'] + 1})
        self.assertEqual(clip_deadlines(record, record['clips'][clip_id])['deliverySeconds'], 2400)
        self.assertIn('40-minute', phase_refusal(record, record['clips'][clip_id], 2401))
        if derived:
            self.assertIsNone(phase_refusal(record, record['clips']['L'], 2401))
            self.assertEqual(record['production']['tasks']['long-author']['state'], 'ready')

    def test_standalone_short_last_slot_claim_is_unchanged(self) -> None:
        """The last host slot remains available to an ordinary standalone Short reviewer."""
        self.assert_short_claim(False)

    def test_derived_short_last_slot_and_own_deadline_are_unchanged(self) -> None:
        """An unfinished Long neither reserves the derived Short's slot nor lends it extra time."""
        self.assert_short_claim(True)


if __name__ == '__main__':
    unittest.main()
