"""Admission rules: per-clip counters, minute 25/40, retries, nested charges, forecasts, outcomes."""
from __future__ import annotations

import hashlib
import re
import unittest
from dataclasses import replace
from unittest import mock

from _budget_fixture import FakeClock, approval, fake_clock, shared_transcript, source_sha, transcript_words, write_transcript
from studio import native_budget_forecast as forecast
from studio import native_budget_launch as launch
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import (
    BatchSpec, admit_dispatch, admit_new_clip, approval_differences, change_approval, charge, close_refusal,
    new_batch_record, new_clip, phase_refusal,
)
from studio.native_budget_schema import validate_record
from studio.native_budget_schema import approval_script
from studio.native_budget_selection import approval_identity, compare_approval, script_identity, title_identity

ALIVE = {'pid': 4242, 'pgid': 4242, 'started': 'Sun Sep 27 09:00:00 2026'}


def batch(slots: int = 1) -> dict:
    """A five-clip batch started now."""
    with fake_clock(FakeClock()):
        return new_batch_record(BatchSpec('batch-test', ('A', 'B', 'C', 'D', 'E'), ('a' * 64,), slots),
                                start_anchor())


def request(clip: str = 'A', route: str = 'final', identity: str = 'id-1', seconds: float = 30.0) -> launch.LaunchRequest:
    return launch.LaunchRequest(clip, route, identity, ('/p', '/o'), seconds)


def running(route: str, admitted: float, granted: float, seconds: float = 30.0) -> dict:
    """A foreign running launch as the forecast sees it."""
    return {'id': f'{route}-{admitted}', 'status': 'running', 'route': route, 'admittedElapsed': admitted,
            'grantedSeconds': granted, 'outputSeconds': seconds, 'supervisor': dict(ALIVE), 'project': '/p',
            'completedElapsed': None, 'stages': [{'phase': 'TEST', 'status': 'TEST'}]}


class AdmissionTests(unittest.TestCase):
    """Decisions over in-memory records; the supervisor identity is stubbed."""

    def setUp(self) -> None:
        patches = [mock.patch.object(launch, 'own_identity', return_value=dict(ALIVE)),
                   mock.patch.object(launch, '_process_table', return_value={4242: (1, 4242, ALIVE['started'])})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def finish(self, record: dict, decision: object, status: str, category: str | None = None) -> None:
        attempt = decision.detail['attempt']
        outcome = {'status': status, 'failureCategory': category, 'errorType': 'RuntimeError',
                   'error': 'Native pipeline failed at /tmp/x 12', 'successStatuses': ('ok',)}
        launch.record_outcome(record, {'clipId': 'A', 'attemptId': attempt['id']}, outcome, 100)

    def test_record_validates_and_rejects_corruption(self) -> None:
        record = batch()
        validate_record(record)
        record['clips']['A']['counters']['exportAttempt'] = -3
        with self.assertRaises(ValueError):
            validate_record(record)

    def test_dispatch_limits_are_per_clip_ceilings(self) -> None:
        record = batch()
        for _ in range(3):
            self.assertTrue(admit_dispatch(record, 'A', 'author', 10).allowed)
            charge(record['clips']['A'], 'author')
        refused = admit_dispatch(record, 'A', 'author', 10)
        self.assertFalse(refused.allowed)
        self.assertIn('author limit reached', refused.reason)
        self.assertTrue(admit_dispatch(record, 'B', 'author', 10).allowed)

    def test_no_creative_work_after_minute_25_but_reviews_continue(self) -> None:
        record = batch()
        for kind in ('author', 'planReview', 'repairCycle'):
            self.assertFalse(admit_dispatch(record, 'A', kind, 1500).allowed)
        self.assertTrue(admit_dispatch(record, 'A', 'review', 1500).allowed)
        self.assertFalse(admit_dispatch(record, 'A', 'review', 2400).allowed)

    def test_a_shorts_only_record_keeps_todays_deadlines(self) -> None:
        from studio.production import formats
        record = batch()
        self.assertEqual(record['schemaVersion'], 7)  # P0 adapt: src's schema 7 lifts 5/6 (native_budget_schema.py:25-26)
        self.assertIs(formats.clip_deadlines(record, record['clips']['A']), record['deadlines'])
        self.assertEqual(formats.clip_deadlines(record, None), record['deadlines'])
        self.assertIs(formats.clip_limits(record, record['clips']['A']), record['limits'])
        self.assertIs(formats.clip_rates(record, record['clips']['A']), record['rates'])
        self.assertRegex(phase_refusal(record, record['clips']['A'], 2400), '^The 40-minute delivery deadline')
        self.assertRegex(admit_dispatch(record, 'A', 'author', 1500).reason, '^Minute 25 has passed')

    def test_new_clips_are_refused_after_minute_25(self) -> None:
        self.assertTrue(admit_new_clip(batch(), 'F', 100).allowed)
        self.assertFalse(admit_new_clip(batch(), 'F', 1500).allowed)
        self.assertFalse(admit_new_clip(batch(), 'A', 100).allowed)

    def test_close_needs_every_clip_handed_off_or_the_deadline(self) -> None:
        record = batch()
        self.assertIn('cannot be closed', close_refusal(record, 60))
        self.assertIsNone(close_refusal(record, 2400))
        for clip in record['clips'].values():
            clip['state'] = 'handed-off'
        self.assertIsNone(close_refusal(record, 60))

    def test_unknown_clip_is_refused_not_created(self) -> None:
        with self.assertRaisesRegex(ValueError, 'add-clip'):
            admit_dispatch(batch(), 'Z', 'author', 0)

    def test_launch_is_charged_even_when_it_later_fails(self) -> None:
        record = batch()
        decision = launch.admit_launch(record, request(), 0)
        self.assertTrue(decision.allowed)
        self.finish(record, decision, 'failed', 'renderer-failure')
        self.assertEqual(record['clips']['A']['counters']['exportAttempt'], 1)

    def test_unchanged_deterministic_failure_gets_zero_retries(self) -> None:
        record = batch()
        self.finish(record, launch.admit_launch(record, request(), 0), 'failed', 'renderer-failure')
        refused = launch.admit_launch(record, request(), 10)
        self.assertFalse(refused.allowed)
        self.assertIn('Unchanged deterministic failure', refused.reason)
        self.assertTrue(launch.admit_launch(record, request(identity='id-2'), 10).allowed)

    def test_one_transient_retry_across_the_clip(self) -> None:
        record = batch()
        self.finish(record, launch.admit_launch(record, request(route='preview'), 0), 'failed',
                    'host-memory-pressure')
        retry = launch.admit_launch(record, request(route='preview'), 10)
        self.assertTrue(retry.allowed)
        self.assertEqual(record['clips']['A']['counters']['transientRetry'], 1)
        self.finish(record, retry, 'failed', 'capacity-timeout')
        self.assertFalse(launch.admit_launch(record, request(route='preview'), 20).allowed)

    def test_export_attempts_cap_counts_drafts_finals_and_failures(self) -> None:
        record = batch()
        self.finish(record, launch.admit_launch(record, request(route='draft'), 0), 'ok')
        self.finish(record, launch.admit_launch(record, request(route='final', identity='x'), 10), 'failed')
        refused = launch.admit_launch(record, request(route='promote', identity='y'), 20)
        self.assertFalse(refused.allowed)
        self.assertIn('exportAttempt limit reached', refused.reason)

    def test_one_running_launch_per_family(self) -> None:
        record = batch()
        self.assertTrue(launch.admit_launch(record, request(route='preview', identity='p'), 0).allowed)
        self.assertIn('already has a running previewLaunch launch',
                      launch.admit_launch(record, request(route='preview', identity='p2'), 5).reason)
        self.assertTrue(launch.admit_launch(record, request(route='draft', identity='d'), 5).allowed)
        for route in ('final', 'draft', 'promote'):
            self.assertIn('already has a running exportAttempt launch',
                          launch.admit_launch(record, request(route=route, identity='x'), 6).reason)
        self.assertEqual(record['clips']['A']['counters']['previewLaunch'], 1)
        self.assertEqual(record['clips']['A']['counters']['exportAttempt'], 1)

    def test_a_preview_beside_a_same_project_draft_is_followed_by_its_promotion(self) -> None:
        record = batch(slots=3)
        draft = request(route='draft', identity='d')
        self.assertTrue(launch.admit_launch(record, draft, 0).allowed)
        project = draft.paths[0]
        self.assertIsNotNone(forecast.promotable_draft_end(record, 'A', project, 0))
        self.assertIsNone(forecast.promotable_draft_end(record, 'A', '/TEST/another-folder', 0))
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=3):
            same = forecast.launch_fits(record, ('A', 'preview', 30.0, project), 0)
            other = forecast.launch_fits(record, ('A', 'preview', 30.0, '/TEST/another-folder'), 0)
            unknown = forecast.launch_fits(record, ('A', 'preview', 30.0), 0)
        promote, final = (round(forecast.route_seconds(record['rates'], route, 30.0), 1) for route in ('promote', 'final'))
        self.assertEqual(same['followingExportSeconds'], promote)
        self.assertEqual((other['followingExportSeconds'], unknown['followingExportSeconds']), (final, final))

    def test_the_promotion_waits_for_a_draft_that_ends_after_the_preview(self) -> None:
        record = batch(slots=3)
        draft = request(route='draft', identity='d', seconds=120.0)
        self.assertTrue(launch.admit_launch(record, draft, 0).allowed)
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=3):
            fit = forecast.launch_fits(record, ('A', 'preview', 30.0, draft.paths[0]), 0)
        draft_end = forecast.route_seconds(record['rates'], 'draft', 120.0)
        self.assertAlmostEqual(fit['forecastFinishElapsed'],
                               round(draft_end + forecast.route_seconds(record['rates'], 'promote', 30.0), 1), places=0)

    def test_a_finished_sibling_that_held_the_lane_is_replayed_at_its_real_finish(self) -> None:
        record = batch()  # one slot: the draft ran first, the preview queued behind it
        record['clips']['A']['attempts'].append(dict(running('draft', 900, 1380), status='succeeded',
                                                     completedElapsed=1250.0))
        record['clips']['A']['attempts'].append(running('preview', 901, 1380))
        preview = forecast.route_seconds(record['rates'], 'preview', 30.0)
        self.assertAlmostEqual(forecast.queue_start_delay(record, 1260), 1250 + preview - 1260, places=3)

    def test_a_preview_that_finished_first_never_erases_its_running_draft(self) -> None:
        record = batch()  # one slot ran the preview first; the draft started when it finished
        record['clips']['A']['attempts'].append(running('draft', 900, 1380))
        record['clips']['A']['attempts'].append(dict(running('preview', 901, 1380), status='succeeded',
                                                     completedElapsed=1342.0))
        draft = forecast.route_seconds(record['rates'], 'draft', 30.0)
        self.assertAlmostEqual(forecast.queue_start_delay(record, 1400), 1342 + draft - 1400, places=3)

    def test_an_early_failure_never_erases_another_clips_running_final(self) -> None:
        record = batch()
        record['clips']['B']['attempts'].append(running('final', 1000, 1280))
        record['clips']['C']['attempts'].append(dict(running('draft', 1010, 1270), status='failed',
                                                     completedElapsed=1015.0))
        self.assertGreater(forecast.queue_start_delay(record, 1400),
                           1000 + forecast.route_seconds(record['rates'], 'final', 30.0) - 1400 - 1)

    def test_equal_admission_times_of_running_and_finished_launches_replay(self) -> None:
        record = batch()
        record['clips']['A']['attempts'].append(running('draft', 900, 1380))
        record['clips']['B']['attempts'].append(dict(running('draft', 900, 1380), status='succeeded',
                                                     completedElapsed=1000.0))
        self.assertGreaterEqual(forecast.queue_start_delay(record, 1100), 0.0)

    def test_an_overrunning_draft_is_still_running_now(self) -> None:
        record = batch(slots=3)
        record['clips']['A']['attempts'].append(running('draft', 0, 2280))
        self.assertEqual(forecast.promotable_draft_end(record, 'A', '/p', 2000), 2000)

    def delivered_draft(self, record: dict) -> None:
        """Clip A's same-project draft (on /p) succeeded with a delivery at 900 s."""
        decision = launch.admit_launch(record, request(route='draft', identity='d'), 500)
        outcome = {'status': 'ok', 'successStatuses': ('ok',),
                   'delivery': {'kind': 'draft', 'output': '/o/review-draft.mp4', 'sha256': 'a' * 64}}
        launch.record_outcome(record, {'clipId': 'A', 'attemptId': decision.detail['attempt']['id']}, outcome, 900)

    def test_status_advises_waiting_then_promoting_a_same_project_pair(self) -> None:
        from studio.native_budget_report import batch_status
        record = batch(slots=3)
        self.delivered_draft(record)
        preview = launch.admit_launch(record, request(route='preview', identity='p'), 950)
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=3):
            waiting = batch_status(record, 1000)['clips']['A']['actions']
            self.finish(record, preview, 'ok')
            promote = batch_status(record, 1100)['clips']['A']['actions']
        self.assertIn('wait for its motion review', waiting[0])
        self.assertTrue(promote[0].startswith('when the moving preview'))
        self.assertIn('native_batch.py handoff', promote[0])

    def test_a_launch_that_stopped_before_any_stage_never_held_the_lane(self) -> None:
        record = batch()
        record['clips']['B']['attempts'].append(dict(running('final', 1000, 1280), stages=[]))
        record['clips']['C']['attempts'].append(dict(running('draft', 1300, 980), status='failed',
                                                     completedElapsed=1305.0, stages=[]))
        final = forecast.route_seconds(record['rates'], 'final', 30.0)
        self.assertAlmostEqual(forecast.queue_start_delay(record, 1310), 1000 + final - 1310, places=3)

    def test_no_promotion_advice_without_a_full_program_launch_left(self) -> None:
        from studio.native_budget_report import batch_status
        record = batch(slots=3)
        self.delivered_draft(record)
        preview = launch.admit_launch(record, request(route='preview', identity='p'), 950)
        self.finish(record, preview, 'ok')
        record['clips']['A']['counters']['exportAttempt'] = 2
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=3):
            advice = batch_status(record, 1100)['clips']['A']['actions']
        self.assertTrue(advice[0].startswith('no full-program launch is left'))

    def test_a_clips_own_running_preview_holds_a_slot_for_its_draft(self) -> None:
        record = batch()
        preview = launch.admit_launch(record, request(route='preview', identity='p'), 0)
        self.assertTrue(preview.allowed)
        with mock.patch.object(forecast, 'slot_count', return_value=1):
            delay = forecast.queue_start_delay(record, 10)
        self.assertAlmostEqual(delay, forecast.route_seconds(record['rates'], 'preview', 30.0) - 10, places=3)

    def test_dead_supervisor_is_abandoned_and_stays_charged(self) -> None:
        record = batch()
        launch.admit_launch(record, request(), 0)
        with mock.patch.object(launch, '_process_table', return_value={}):
            self.assertTrue(launch.admit_launch(record, request(identity='id-2'), 30).allowed)
        self.assertEqual(record['clips']['A']['attempts'][0]['status'], 'abandoned')
        self.assertEqual(record['clips']['A']['counters']['exportAttempt'], 2)

    def test_real_outcome_replaces_an_abandoned_mark(self) -> None:
        record = batch()
        decision = launch.admit_launch(record, request(), 0)
        with mock.patch.object(launch, '_process_table', return_value={}):
            launch.reconcile_running(record, 50)
        self.finish(record, decision, 'ok')
        self.assertEqual(record['clips']['A']['attempts'][0]['status'], 'succeeded')

    def test_process_table_is_read_with_a_fixed_clock_and_locale(self) -> None:
        self.assertEqual(launch.PS_ENVIRONMENT['TZ'], 'UTC')
        self.assertEqual(launch.PS_ENVIRONMENT['LC_ALL'], 'C')

    def test_no_preview_after_minute_25(self) -> None:
        self.assertIn('Minute 25', launch.admit_launch(batch(), request(route='preview'), 1500).reason)

    def test_forecast_refusal_names_the_review_draft(self) -> None:
        record = batch()
        refused = launch.admit_launch(record, request(route='final', seconds=60.0), 1900)
        self.assertFalse(refused.allowed)
        self.assertIn('--review-draft', refused.reason)
        self.assertTrue(launch.admit_launch(record, request(route='draft', seconds=60.0), 1500).allowed)

    def test_refused_launch_does_not_rewrite_the_clip_duration(self) -> None:
        record = batch()
        record['clips']['A']['outputSeconds'] = 55.0
        launch.admit_launch(record, request(route='final', seconds=10.0), 2300)
        self.assertEqual(record['clips']['A']['outputSeconds'], 55.0)

    def test_queue_ahead_on_one_slot_is_sequential(self) -> None:
        record = batch()
        for clip in 'BCDE':
            record['clips'][clip]['attempts'].append(running('final', 0, 2280, seconds=60.0))
        delay = forecast.queue_start_delay(record, 0)
        self.assertAlmostEqual(delay, 4 * forecast.route_seconds(record['rates'], 'final', 60.0), places=3)
        self.assertFalse(launch.admit_launch(record, request(route='final', seconds=60.0), 0).allowed)

    def test_overrunning_launch_holds_its_slot_until_its_grant_ends(self) -> None:
        record = batch()
        record['clips']['B']['attempts'].append(running('final', 0, 2280, seconds=60.0))
        self.assertAlmostEqual(forecast.queue_start_delay(record, 1100), 2280 - 1100)

    def test_pool_slots_never_exceed_the_real_heavy_lane(self) -> None:
        record = batch(slots=3)
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1):
            self.assertEqual(forecast.slot_count(record), 1)
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=5):
            self.assertEqual(forecast.slot_count(record), 3)

    def test_forecast_needs_a_known_duration(self) -> None:
        with self.assertRaisesRegex(ValueError, 'known authored duration'):
            forecast.route_seconds(batch()['rates'], 'final', None)

    def test_nested_picture_and_aac_limits(self) -> None:
        record = batch()
        decision = launch.admit_launch(record, request(), 0)
        binding = {'clipId': 'A', 'attemptId': decision.detail['attempt']['id']}
        for _ in range(2):
            self.assertTrue(launch.charge_nested(record, binding, 'pictureGeneration').allowed)
        self.assertFalse(launch.charge_nested(record, binding, 'pictureGeneration').allowed)
        audio = ['1' * 64, '2' * 64, '3' * 64]
        for _ in range(3):
            self.assertTrue(launch.charge_nested(record, binding, 'aacCandidate', audio[0]).allowed)
        self.assertFalse(launch.charge_nested(record, binding, 'aacCandidate', audio[0]).allowed)
        for _ in range(3):
            self.assertTrue(launch.charge_nested(record, binding, 'aacCandidate', audio[1]).allowed)
        self.assertFalse(launch.charge_nested(record, binding, 'aacCandidate', audio[2]).allowed)

    def test_outcome_is_recorded_exactly_once(self) -> None:
        record = batch()
        decision = launch.admit_launch(record, request(), 0)
        self.finish(record, decision, 'ok')
        with self.assertRaisesRegex(ValueError, 'already recorded'):
            self.finish(record, decision, 'ok')

    def test_failure_signature_ignores_volatile_paths_and_numbers(self) -> None:
        first = launch.failure_signature('RuntimeError', 'bad frame 12 at /tmp/a/b.mp4 (sha 0123456789abcdef0123)')
        second = launch.failure_signature('RuntimeError', 'bad frame 99 at /tmp/c.mp4 (sha fedcba9876543210fedc)')
        self.assertEqual(first, second)

    def test_handed_off_clip_admits_no_polish(self) -> None:
        record = batch()
        record['clips']['A']['state'] = 'handed-off'
        self.assertIn('handed off', launch.admit_launch(record, request(), 10).reason)
        self.assertFalse(admit_dispatch(record, 'A', 'repairCycle', 10).allowed)

    def test_closed_batch_admits_nothing(self) -> None:
        record = batch()
        record['status'] = 'closed'
        self.assertIn('closed', launch.admit_launch(record, request(), 10).reason)



class ProductionPolicyTests(unittest.TestCase):
    """Schema version 4 policy: approvals bound at start, AI allowance, draining refusals."""

    def approved(self, clips: tuple = ('A', 'B')) -> dict:
        spec = BatchSpec('batch-test', clips, ('a' * 64,), 1, approvals={clip: approval(clip) for clip in clips})
        with fake_clock(FakeClock()):
            return new_batch_record(spec, start_anchor())

    def test_start_binds_each_clips_approved_title_and_script(self) -> None:
        record = self.approved()
        row = record['clips']['A']['approvals'][0]
        self.assertEqual((row['title'], row['titleSha256'], row['wordRanges'], row['wordCount']),
                         ('TEST title A', title_identity('TEST title A'), [[10, 39], [50, 79]], 60))
        self.assertEqual((row['ranges'], row['wordTexts'][:2], row['transcriptWords']),
                         ([[10.0, 40.0], [50.0, 80.0]], ['w10', 'w11'], 2000))
        self.assertEqual(row['script'], script_identity(approval_script(row)))
        self.assertEqual(row['identity'], approval_identity('TEST title A', row['script']))
        self.assertEqual((row['elapsed'], row['epoch'], row['recordedBy']), (0.0, record['startEpoch'],
                                                                              'TEST coordinator'))
        validate_record(record)
        with self.assertRaisesRegex(ValueError, 'every declared clip'):
            new_batch_record(BatchSpec('batch-test', ('A', 'B'), (), 1, approvals={'A': approval('A')}),
                             start_anchor())

    def start_with(self, value: object) -> dict:
        return new_batch_record(BatchSpec('batch-test', ('A',), (), 1, approvals={'A': value}), start_anchor())

    def test_titles_follow_the_user_title_contract_and_keep_their_exact_bytes(self) -> None:
        for title in ('x' * 121, '\U0001F600' * 61, 'two\nlines', 'sep\u2028arator', 'nel\x85', 'del\x7f',
                      '   ', '\ufeff', '\ud800'):
            with self.assertRaisesRegex(ValueError, 'title', msg=repr(title)):
                self.start_with(approval('A', title))
        for exact in ('Cafe\u0301 two  spaces ', '\U0001F600' * 60, '\U0001F468\u200d\U0001F469 family'):
            self.assertEqual(self.start_with(approval('A', exact))['clips']['A']['approvals'][0]['title'], exact)

    def test_scripts_are_ordered_non_overlapping_in_range_and_fully_texted(self) -> None:
        cases = {'overlap': {'word_ranges': ((10, 39), (30, 79))}, 'range': {'word_ranges': ((10, 2000),)},
                 'texts': {'word_texts': ('only',)}, 'seconds': {'ranges': ((10.0, 40.0),)},
                 'crossing': {'ranges': ((10.0, 60.0), (50.0, 80.0))}}
        for name, change in cases.items():
            with self.assertRaisesRegex(ValueError, 'Approval refused', msg=name):
                self.start_with(approval('A', **change))
        texts = tuple(f'w{index}' for index in [*range(50, 80), *range(10, 40)])
        reordered = self.start_with(approval('A', word_ranges=((50, 79), (10, 39)), word_texts=texts,
                                             ranges=((50.0, 80.0), (10.0, 40.0))))
        self.assertNotEqual(reordered['clips']['A']['approvals'][0]['script'],
                            self.approved()['clips']['A']['approvals'][0]['script'])

    def over(self, words: list[dict], **changes: object) -> object:
        """The clip-A TEST approval bound over a transcript with these words."""
        import tempfile
        from pathlib import Path
        directory = Path(tempfile.mkdtemp(dir=str(Path(shared_transcript()[0]).parent)))
        path = directory / 'transcript.json'
        digest = write_transcript(path, words)
        return approval('A', transcript_path=str(path), transcript_sha256=digest, **changes)

    def test_binding_refuses_a_transcript_whose_word_numbering_differs_from_the_writers(self) -> None:
        cases = {'drops words [5]': lambda words: words[5].update(end=words[5]['start']),
                 'drops words [7]': lambda words: words[7].update(end=words[7]['start'] + 1e-6),
                 'drops words [1999]': lambda words: words[1999].update(start=2000.0, end=2000.4),
                 'drops words [3]': lambda words: words[3].update(start=-0.5),
                 'reorders words [12]': lambda words: words[12].update(start=4.0, end=5.4)}
        for expected, change in cases.items():
            words = transcript_words()
            change(words)
            with self.assertRaisesRegex(ValueError, 'Approval refused: the transcript is refused because the writer '
                                                    f'.*{re.escape(expected)}', msg=expected):
                self.start_with(self.over(words))
        self.start_with(self.over(transcript_words()))                  # the same words bind

    def test_binding_checks_the_transcript_file_it_names(self) -> None:
        from pathlib import Path
        good = self.over(transcript_words())
        with self.assertRaisesRegex(ValueError, 'SHA-256 differs'):
            self.start_with(replace(good, transcript_sha256='0' * 64))
        with self.assertRaisesRegex(ValueError, 'not the approval.s 2001'):
            self.start_with(replace(good, transcript_words=2001))
        with self.assertRaisesRegex(ValueError, 'word texts are not the transcript'):
            self.start_with(replace(good, word_texts=('x',) + good.word_texts[1:]))
        flat = Path(good.transcript_path).with_name('flat.json')
        flat.write_bytes(b'[{"word": "w0", "start": 0, "end": 1}]')
        with self.assertRaisesRegex(ValueError, 'not an utterance transcript'):
            self.start_with(replace(good, transcript_path=str(flat),
                                    transcript_sha256=hashlib.sha256(flat.read_bytes()).hexdigest()))
        nan = Path(good.transcript_path).with_name('nan.json')
        nan.write_bytes(b'{"transcript": [{"words": [{"word": "w0", "start": NaN, "end": 1}]}]}')
        with self.assertRaisesRegex(ValueError, 'not JSON the writer reads'):
            self.start_with(replace(good, transcript_path=str(nan),
                                    transcript_sha256=hashlib.sha256(nan.read_bytes()).hexdigest()))

    def test_a_later_change_is_refused_over_a_diverging_transcript(self) -> None:
        record = self.approved()
        words = transcript_words()
        words[20].update(end=words[20]['start'])
        with self.assertRaisesRegex(ValueError, 'drops words \\[20\\]'):
            change_approval(record, 'A', self.over(words, title='TEST retitled A'), 300.0)
        self.assertEqual(len(record['clips']['A']['approvals']), 1)

    def test_a_hand_edited_approval_is_corrupt(self) -> None:
        record = self.approved()
        record['clips']['A']['approvals'][0]['wordTexts'][0] = 'edited'
        with self.assertRaisesRegex(ValueError, 'approval identities do not match'):
            validate_record(record)

    def test_the_canonical_form_is_pinned(self) -> None:
        script = {'sourceSha256': 'a' * 64, 'transcriptSha256': 'b' * 64, 'transcriptWords': 10,
                  'wordRanges': [[1, 2]], 'wordTexts': ['caf\u00e9', 'ok'], 'ranges': [[1, 2.5]]}
        body = ('{"sourceSha256":"' + 'a' * 64 + '","transcriptSha256":"' + 'b' * 64 + '","wordRanges":[[1,2]],'
                '"wordTexts":["caf\u00e9","ok"],"ranges":[[1.0,2.5]]}')
        self.assertEqual(script_identity(script), hashlib.sha256(body.encode('utf-8')).hexdigest())
        self.assertEqual(approval_identity('T\u00e9', 'c' * 64), hashlib.sha256(
            ('{"title":"T\u00e9","script":"' + 'c' * 64 + '"}').encode('utf-8')).hexdigest())
        self.assertEqual(title_identity('Why the hook lands'),        # the same as the role packets' text_sha
                         '8da79ee7051b09401eb5f80811a0020c2289dabe303f6f2e178449b725832423')

    def test_plans_and_projects_compare_exactly_with_the_approval(self) -> None:
        row = self.approved()['clips']['A']['approvals'][0]
        same = compare_approval(row, {'title': 'TEST title A', 'script': approval_script(row),
                                      'sourceSha256': source_sha(), 'ranges': [[50, 80], [10, 30], [25, 40]]})
        self.assertEqual(same, {'title': 'exact', 'script': True, 'selection': True})
        other = compare_approval(row, {'title': ' TEST  title A', 'sourceSha256': source_sha(),
                                       'ranges': [[10.0, 40.0], [50.0, 80.5]]})
        self.assertEqual(other, {'title': 'normalization-only', 'script': None, 'selection': False})
        self.assertEqual(compare_approval(row, {'title': 'TEST title B'})['title'], 'different')

    def test_a_later_change_is_a_typed_change_beside_the_start_approval(self) -> None:
        record = self.approved()
        clock = dict(record['clock'])
        spaced = change_approval(record, 'A', approval('A', 'TEST  title A'), 300.0)
        self.assertEqual((spaced['changed'], spaced['material']), (['title-normalization'], False))
        retitled = change_approval(record, 'A', approval('A', 'TEST retitled A'), 310.0)
        self.assertEqual((retitled['changed'], retitled['material'], retitled['from']),
                         (['title'], True, spaced['to']))
        self.assertEqual((retitled['row']['elapsed'], len(record['clips']['A']['approvals']), record['clock']),
                         (310.0, 3, clock))
        self.assertIn('already has this exact', change_approval(record, 'A', approval('A', 'TEST retitled A'),
                                                                320.0)['refusal'])
        record['clips']['B']['state'] = 'handed-off'
        self.assertIn('handed off', change_approval(record, 'B', approval('B', 'x'), 320.0)['refusal'])
        record['clips']['C'] = new_clip('added without approval', True)
        self.assertIn('no approved title', change_approval(record, 'C', approval('C'), 330.0)['refusal'])
        validate_record(record)

    def test_ai_allowance_defaults_and_ceilings(self) -> None:
        production = self.approved(('A', 'B', 'C', 'D', 'E'))['production']
        self.assertEqual(production['ai'], {'slots': 4, 'reservations': 5 * 15 + 8, 'charged': 0})
        for values in ({'ai_slots': 17}, {'ai_slots': 0}, {'ai_reservations': 257}):
            with self.assertRaisesRegex(ValueError, 'AI slots'):
                new_batch_record(BatchSpec('batch-test', ('A',), (), 1, **values), start_anchor())

    def test_draining_refuses_new_work_and_needs_its_drain_record(self) -> None:
        record = batch()
        record['status'] = 'draining'
        with self.assertRaisesRegex(ValueError, 'drain record'):
            validate_record(record)
        record['production']['drain'] = {'startedElapsed': 2400.0, 'reason': 'close requested'}
        validate_record(record)
        self.assertIn('draining', phase_refusal(record, None, 100))
        self.assertIn('draining', admit_dispatch(record, 'A', 'review', 100).reason)
        self.assertIn('draining', launch.admit_launch(record, request(), 100).reason)
        self.assertEqual(admit_new_clip(record, 'F', 100).reason, 'The batch is draining')
        self.assertIsNone(close_refusal(record, 2400))
        from studio.native_budget_report import phase
        self.assertEqual(phase(record, 100), 'draining')
        record.update(status='closed', closedAtElapsed=2500.0)
        self.assertEqual(close_refusal(record, 2600), 'The batch is already closed')


class MediaRequestTests(unittest.TestCase):
    """run-media accepts typed allowlisted delivering routes only; the exporter's own parser and option
    checks accept the arguments and derive the same route (unit A3)."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        (self.base / 'project').mkdir()
        self.project, self.output = str(self.base / 'project'), str(self.base / 'attempt')

    def request(self, route: str, **options: object) -> dict:
        from studio.production import media
        value = {'schemaVersion': 1, 'kind': 'native-media-request', 'batchId': 'batch-auth', 'taskId': 'm1',
                 'clipId': 'A', 'route': route, 'project': self.project, 'output': self.output,
                 'options': options}
        import json
        return media.parse_request(json.dumps(value).encode(), 'TEST request')

    def test_every_route_maps_to_the_exporters_own_arguments(self) -> None:
        from studio.production import media
        cases = {'draft': {'draftFindings': '/TEST/findings.json', 'cache': '/TEST/cold-cache'},
                 'final': {'previewReviews': '/TEST/reviews.json', 'cachedNativeBatches': True},
                 'promote': {'promoteDraft': '/TEST/draft', 'previewReviews': '/TEST/reviews.json'},
                 'verify': {'verifyFrom': '/TEST/a/render-stage.json'}, 'resume': {'resumeFrom': '/TEST/a'}}
        for route, options in cases.items():
            with self.subTest(route=route):
                arguments = media.exporter_arguments(self.request(route, **options))
                self.assertEqual(arguments[:2], [self.project, self.output])
                media.check_route(arguments, route)
        self.assertEqual(media.exporter_arguments(self.request('draft')), [self.project, self.output,
                                                                           '--review-draft'])
        self.assertIn('--cache', media.exporter_arguments(self.request('draft', cache='/TEST/cold-cache')))

    def test_a_preview_is_not_a_media_task(self) -> None:
        with self.assertRaisesRegex(ValueError, 'native_export.py --preview-only'):
            self.request('preview')

    def test_unlisted_untyped_or_incomplete_requests_are_refused(self) -> None:
        refused = [('draft', {'pictureDonor': '/TEST/d'}), ('draft', {'renderOnly': True}),
                   ('final', {}), ('promote', {'promoteDraft': '/TEST/d'}), ('final', {'previewReviews': 'rel.json'}),
                   ('draft', {'cachedNativeBatches': False}), ('transcode', {}),
                   ('final', {'previewReviews': '/TEST/../etc/r.json'}), ('draft', {'cache': 'relative/cache'})]
        for route, options in refused:
            with self.subTest(route=route, options=options), self.assertRaises(ValueError):
                self.request(route, **options)

    def test_arguments_the_exporter_reads_as_another_route_are_refused(self) -> None:
        from studio.production import media
        with self.assertRaisesRegex(ValueError, 'refuses these arguments'):
            media.check_route(media.exporter_arguments(self.request('draft', promoteDraft='/TEST/d',
                                                                    previewReviews='/TEST/r.json')), 'draft')
        with self.assertRaisesRegex(ValueError, 'launch route draft, not'):
            media.check_route([self.project, self.output, '--review-draft'], 'final')

    def test_the_exporters_own_option_checks_refuse_before_enqueue(self) -> None:
        from studio.production import media
        with self.assertRaisesRegex(ValueError, 'preserves the sealed route, cache'):
            media.check_route(media.exporter_arguments(self.request('verify', verifyFrom='/TEST/a/render-stage.json',
                                                                    cache='/TEST/cache')), 'verify')
        with self.assertRaisesRegex(ValueError, 'requires --cached-native-batches'):
            media.check_route(media.exporter_arguments(self.request('draft', acquireSourceCache=True)), 'draft')
        (self.base / 'attempt').mkdir()
        with self.assertRaisesRegex(ValueError, 'new directory outside the authored project'):
            media.check_route(media.exporter_arguments(self.request('draft')), 'draft')

    def test_a_revision_request_is_decided_by_the_exporters_own_parser(self) -> None:
        from studio.production import media
        from studio.native_short_export import parser
        arguments = media.exporter_arguments(self.request('draft', reviseFrom='/TEST/attempt-v1'))
        self.assertEqual(arguments[-2:], ['--revise-from', '/TEST/attempt-v1'])
        if any('--revise-from' in action.option_strings for action in parser()._actions):
            media.check_route(arguments, 'draft')   # F1's route: the same claim, watchdog and route derivation
        else:
            with self.assertRaisesRegex(ValueError, 'unrecognized arguments: --revise-from'):
                media.check_route(arguments, 'draft')


if __name__ == '__main__':
    unittest.main()
