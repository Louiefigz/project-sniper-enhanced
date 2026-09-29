"""In-run budget hooks: bounded owners, hard deadline, nested charges and the outcome."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import FakeClock, b3_stand_in, fake_clock, handoff_confirmation, make_project, test_mp4
from _native_short_pipeline_fixture import ShortPipelineFixture, isolate_early_checks
from studio.native_budget_clock import BudgetExhausted, allocation, start_anchor
from studio.native_budget_owner import aac_budget_hook, budget_owner_settings
from studio.native_run_lifecycle import failure_category
from studio.native_short_pipeline import FINAL_STATUS, NativeShortPipeline
from test_native_budget_registry import RegistryCase, ns
import native_batch
from studio import native_budget_binding as binding
from studio import native_budget_owner as owner_budget
from studio.native_budget_registry import BudgetRefused


class BudgetedPipelineTests(unittest.TestCase):
    """The real coordinator with TEST owners; only the budget authority is stubbed."""

    def setUp(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.fixture = ShortPipelineFixture(base)
        isolate_early_checks(self)
        self.enterContext(mock.patch('studio.native_short_pipeline.NativeRun',
                                     side_effect=self.fixture.owner_factory))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.clock = self.enterContext(fake_clock(FakeClock()))
        self.charges = []
        # P0 (X118, M-033): patch the preview sections first. Its module-level import binds charge_request when it is
        # first imported; importing it under the binding patch would leave that mock in place after this test.
        self.enterContext(mock.patch('studio.native_preview_sections.charge_request',
                                     side_effect=lambda request, kind: self.charges.append(kind)))
        self.enterContext(mock.patch('studio.native_budget_binding.charge_request',  # P0 adapt: lazy import
                                     side_effect=lambda request, kind: self.charges.append(kind)))
        self.outcomes = []
        self.enterContext(mock.patch('studio.native_short_pipeline.record_budget_outcome',
                                     side_effect=lambda request, result: self.outcomes.append(result['status'])))

    def budgeted(self, granted: float) -> dict:
        grant = allocation(start_anchor(), granted, 45)
        request = {**self.fixture.request, 'productionBudget': {'allocation': grant, 'batchId': 'b', 'clipId': 'A'}}
        self.fixture.write_request(request)  # the exporter publishes the budgeted request exactly like this
        return request

    def test_every_owner_inherits_the_remaining_deadline_and_queues(self) -> None:
        self.assertTrue(NativeShortPipeline(self.budgeted(700), {'TEST_ONLY': '1'}).execute())
        deadlines = [config.deadline for _, config in self.fixture.calls]
        self.assertEqual(deadlines, [655] * 6)  # queue (pool) + work, clamped to the inherited 700 s grant
        for _, config in self.fixture.calls:
            self.assertEqual(config.capacity_wait_seconds, min(600, config.deadline))
            self.assertIsNotNone(config.hard_deadline)
        self.assertEqual(self.charges, ['previewPackage', 'pictureGeneration'])
        self.assertEqual(self.outcomes, [FINAL_STATUS])

    def test_exhausted_deadline_fails_the_launch_before_the_next_owner(self) -> None:
        self.assertFalse(NativeShortPipeline(self.budgeted(40), {'TEST_ONLY': '1'}).execute())
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(self.outcomes, ['failed'])

    def test_unbudgeted_pipeline_is_unchanged(self) -> None:
        self.assertTrue(NativeShortPipeline(self.fixture.request, {'TEST_ONLY': '1'}).execute())
        self.assertEqual([config.deadline for _, config in self.fixture.calls], [1200] * 6)  # pool queue + work
        self.assertTrue(all(config.hard_deadline is None for _, config in self.fixture.calls))


class OwnerHookTests(unittest.TestCase):
    """Small units around the owner and audio hooks."""

    def test_owner_settings_raise_when_the_deadline_is_spent(self) -> None:
        with fake_clock(FakeClock()) as now:
            request = {'productionBudget': {'allocation': allocation(start_anchor(), 100, 45)}}
            settings = mock.Mock(deadline=600)
            now.advance(60)
            with self.assertRaises(BudgetExhausted):
                budget_owner_settings(request, settings)

    def test_budget_exhausted_category_survives_owner_finish(self) -> None:
        result = {'status': 'failed', 'cleanup': {'verified': True}, 'abortReason': 'Production deadline reached',
                  'failureCategory': 'budget-exhausted'}
        self.assertEqual(failure_category(result), 'budget-exhausted')

    def test_native_run_hard_deadline_uses_both_clocks(self) -> None:
        from studio.native_run import NativeRun
        with fake_clock(FakeClock()) as now:
            owner = NativeRun.__new__(NativeRun)
            owner.hard_deadline = allocation(start_anchor(), 100, 45)
            owner.result = {}
            from studio.native_budget_clock import BudgetExhausted
            from studio.native_run_lifecycle import require_production_time  # P0 adapt: src's check (capacityClock)
            self.assertGreater(require_production_time(owner), 0)
            now.advance(101, wall=0)  # asleep: wall clock stood still, continuous time ran out
            with self.assertRaises(BudgetExhausted):
                require_production_time(owner)
            self.assertEqual(owner.result['failureCategory'], 'budget-exhausted')

    def test_aac_hook_charges_each_candidate_against_its_exact_audio(self) -> None:
        calls = []
        with mock.patch('studio.native_budget_owner.charge_request',
                        side_effect=lambda request, kind, key: calls.append((kind, key))):
            hook = aac_budget_hook({'productionBudget': {'x': 1}}, 'a' * 64, 'native-short-v1')
            hook(1)
            hook(2)
        self.assertEqual([kind for kind, _ in calls], ['aacCandidate', 'aacCandidate'])
        self.assertEqual(len({key for _, key in calls}), 1)
        self.assertIsNone(aac_budget_hook({}, 'a' * 64, 'native-short-v1'))

    def test_aac_refusal_stops_before_candidate_work(self) -> None:
        from audio import native_dialogue_delivery as delivery
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            request = mock.Mock(directory=Path(temporary), candidate_hook=mock.Mock(side_effect=RuntimeError('refused')))
            receipt = {}
            with mock.patch.object(delivery, '_stable'):
                with self.assertRaisesRegex(RuntimeError, 'refused'):
                    delivery._finish_candidates(request, receipt, ('ffmpeg', 'ffprobe'))
            self.assertEqual(list(Path(temporary).iterdir()), [])
            self.assertEqual(receipt['aacCandidates'], [])


class HandedOffOwnerTests(RegistryCase):
    """After the visible hand-off command, supporting owners of that clip stop; other clips keep their grant."""

    def deliver(self, clip: str, project: Path) -> None:
        budget = self.reserve(project, route='draft', name=f'draft-{clip}')
        self.mp4s = {**getattr(self, 'mp4s', {}), clip: test_mp4(self.work / f'mp4-{clip}', f'{clip}.mp4')}
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-review-draft', 'output': self.mp4s[clip][0], 'sha256': self.mp4s[clip][1]})

    def hand_off(self, clip: str) -> None:
        confirmation = handoff_confirmation(self.work / clip, self.mp4s[clip], at=self.clock.wall)
        with b3_stand_in():
            native_batch.cmd_handoff(ns(batch='batch-auth', clip=clip, confirmation=confirmation))

    def test_a_bundle_serving_a_handed_off_clip_runs_under_the_other_clips_grant(self) -> None:
        other = make_project(self.work, 'native-b', cuts=((300.0, 340.0),))
        binding.bind_project(self.root, 'batch-auth', 'B', other)
        self.deliver('A', self.project)
        self.deliver('B', other)
        self.hand_off('A')
        bundle = SimpleNamespace(hard_deadline=None, project=self.work, label='native-review', deadline=600,
                                 settings=SimpleNamespace(serves=(self.project, other)))
        owner_budget.apply_budget_to_owner(bundle)                    # clip B still admits its hand-off work
        self.assertIsNotNone(bundle.hard_deadline)
        self.hand_off('B')
        bundle.hard_deadline = None
        with self.assertRaisesRegex(BudgetRefused, 'handed off'):
            owner_budget.apply_budget_to_owner(bundle)


if __name__ == '__main__':
    unittest.main()
