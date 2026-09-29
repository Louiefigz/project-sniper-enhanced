"""Review round 3 regressions: staged starts (deadline, leftovers, upgrades, discard) and the settlement room
(launch outcomes, supersession of settled work, read-only observations).

The reserve and staging cases are ports of the adversarial reviewer's probes (test_adv_a12_r2).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import CHANGE_REASON, approval, host_turn, task_spec, write_transcript
from _dispatch_fixture import start_args  # P0 adapt: thin CLI start
from _pending import pending
from test_native_budget_registry import ns
from test_production_tasks import BATCH, TaskCase
import native_batch
from studio import native_budget_forecast as forecast  # P0 adapt: the thin CLI reads it here
from studio import native_budget_batches as batches, native_budget_binding as binding
from studio import native_budget_schema as schema, native_budget_staging as staging
from studio.native_budget_store import BudgetAuthorityError, MAX_RECORD_BYTES
from studio.production.approvals import ApprovalChange  # P0 adapt: src takes one typed change (WAVES:186)
from studio.production import api, settlement
from studio.production.authorization import MAX_STAGED
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.task_schema import authorization_identity

AUTHORITY = 'batches/batch-auth/authority.json'


class StagedStarts(TaskCase):
    """Refused starts staged under batches/: backdating, stale leftovers, the MAX_STAGED bound, upgrades."""

    def start_cli(self, batch_id: str, clips: str = 'A') -> dict:
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1):
            return native_batch.cmd_start(start_args(self.work, batch_id, clips))  # P0 adapt: thin CLI start

    def close_auth(self) -> None:
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))
        self.clock.advance(2400)
        native_batch.cmd_close(ns(batch=BATCH))

    def staged(self) -> list[str]:
        return sorted(entry.name for entry in (self.root / 'batches').iterdir() if entry.name.startswith('.creating'))

    def discarded(self) -> list[str]:
        directory = self.root / 'archive' / staging.DISCARDED
        return sorted(entry.name for entry in directory.iterdir()) if directory.is_dir() else []

    @pending('P3b', "A12 R4-12: studio/production/commands.py:96-99 cmd_start drops authorize()'s "
                    "discardedStagings and priorAuthorizations (P0 Step 4.4, owner P3b)")
    def test_a_day_old_refused_start_is_not_adopted_as_a_new_go(self) -> None:
        handover = self.clock.wall
        with self.assertRaises(batches.PredecessorCurrent):
            self.start_cli('batch-next')
        name = self.staged()[0]
        self.close_auth()
        self.clock.advance(86400)                                  # the operator hands over again tomorrow
        started = self.start_cli('batch-next')
        self.assertEqual((started['resumed'], started['authorizedAtEpoch']), (False, self.clock.wall))
        self.assertNotEqual(started['authorizedAtEpoch'], handover)
        self.assertEqual(([row['name'] for row in started['discardedStagings']], self.staged(), self.discarded()),
                         ([name], [], [name[1:]]))
        miss = started['discardedStagings'][0]['miss']
        self.assertEqual((miss['cause'], miss['authorizedAtEpoch'], miss['deadlineEpoch']),
                         ('expired', handover, handover + 2400))
        self.assertEqual(started['priorAuthorizations'], [miss])                      # a fresh clock never hides it
        trail = (self.root / 'archive' / staging.DISCARDED / name[1:] / 'events.jsonl').read_bytes().splitlines()
        self.assertEqual([json.loads(line)['event'] for line in trail], ['batch-started', 'staging-discarded'])

    def test_a_superseded_staging_does_not_linger(self) -> None:
        with self.assertRaises(batches.PredecessorCurrent):
            self.start_cli('batch-next')                           # staged: clips A
        self.close_auth()
        self.start_cli('batch-next', 'A,B')                        # operator corrected the clip list: new anchor
        self.assertEqual(self.staged(), [], f'stale staging left behind: {self.staged()}')

    def test_refusal_storm_then_recording_still_works(self) -> None:
        for index in range(MAX_STAGED):
            with self.assertRaises(batches.PredecessorCurrent):
                self.start_cli(f'batch-wait-{index}')
        self.close_auth()                                          # the operator starts none of the eight
        self.start_cli('batch-real')
        with self.assertRaisesRegex(batches.BudgetRefused, 'is recorded'):
            self.start_cli('batch-after')                          # refused behind batch-real, still recorded
        self.assertEqual(len(self.discarded()), MAX_STAGED)

    def test_a_staged_start_survives_an_engine_upgrade(self) -> None:
        with self.assertRaises(batches.PredecessorCurrent):
            self.start_cli('batch-next')
        name = self.staged()[0]
        with mock.patch.object(schema, 'SCHEMA_VERSION', schema.SCHEMA_VERSION + 1):     # the next engine
            self.assertEqual(batches.list_batches(self.root), ['batch-auth'])            # reported, never fatal
            listed = api.staged_starts(self.root)
            self.assertEqual([(row['name'], row['state']) for row in listed], [(name, 'foreign-version')])
            self.assertEqual(staging.adoptable_stagings(self.root), [])                    # never adopted
        discarded = api.discard_staged(self.root, name, 'upgraded engine; handed over again')
        self.assertEqual((discarded['state'], self.staged()), ('adoptable', []))

    @pending('P3b', "A12 R4-12: studio/production/commands.py:96-99 cmd_start drops authorize()'s "
                    "discardedStagings and priorAuthorizations (P0 Step 4.4, owner P3b)")
    def test_a_staging_left_by_another_engine_never_blocks_a_start(self) -> None:
        with self.assertRaises(batches.PredecessorCurrent):
            self.start_cli('batch-next')
        name = self.staged()[0]
        path = self.root / 'batches' / name / 'authority.json'
        path.write_text(json.dumps({**json.loads(path.read_text()), 'schemaVersion': 3}))   # an older engine's
        self.close_auth()
        started = self.start_cli('batch-next')
        self.assertEqual((started['resumed'], started['authorizedAtEpoch']), (False, self.clock.wall))
        self.assertEqual(([(row['name'], row['cause']) for row in started['discardedStagings']], self.staged()),
                         ([(name, 'replaced')], []))                  # replaced by this start's new hand-over

    def test_the_operator_discards_by_exact_name_only(self) -> None:
        with self.assertRaises(batches.PredecessorCurrent):
            self.start_cli('batch-next')
        with self.assertRaisesRegex(ValueError, 'exactly'):
            api.discard_staged(self.root, '.creating-batch-next-*', 'glob')
        with self.assertRaisesRegex(batches.BudgetRefused, 'not a staged start'):
            api.discard_staged(self.root, '.creating-batch-next-000000000000', 'typo')
        with self.assertRaisesRegex(ValueError, 'reason'):
            api.discard_staged(self.root, self.staged()[0], ' ')
        name = self.staged()[0]
        self.assertEqual(api.discard_staged(self.root, name, 'wrong clips')['reason'], 'operator: wrong clips')
        self.assertEqual((self.staged(), self.discarded()), ([], [name[1:]]))

    def test_the_identity_covers_the_ai_slots_and_reservations(self) -> None:
        record = self.record()
        identity = authorization_identity(record)
        for key in ('slots', 'reservations'):
            changed = json.loads(json.dumps(record))
            changed['production']['ai'][key] += 1
            self.assertNotEqual(authorization_identity(changed), identity, key)


class SettlementRoom(TaskCase):
    """Launch outcomes, supersession of settled work and observations never take a task's settlement room."""

    def fill(self) -> int:
        """Grow the record with approval changes and added clips until new work is refused."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        words = [{'word': f'{index:04d}' + 'W' * 60, 'start': float(index), 'end': index + 0.9}
                 for index in range(2000)]
        path = Path(temp.name) / 'long.json'
        sha = write_transcript(path, words)
        capacity, version = {}, 0

        def once(count: int) -> bool:
            ranges = tuple((index, index) for index in range(min(count, 128)))
            if count > len(ranges):
                ranges = ranges[:-1] + ((ranges[-1][0], ranges[-1][0] + count - len(ranges)),)
            kept = [index for first, last in ranges for index in range(first, last + 1)]
            open_clips = [clip for clip, left in capacity.items() if left > 0]
            clip = open_clips[0] if open_clips else f'X{len(capacity)}'
            value = approval(clip, title=f'T{version}-{count}', word_ranges=ranges, transcript_words=2000,
                             word_texts=tuple(words[index]['word'] for index in kept), transcript_path=str(path),
                             transcript_sha256=sha, ranges=tuple((float(first), last + 0.9) for first, last in ranges))
            try:
                if open_clips:
                    api.record_script_change(self.root, BATCH, clip, ApprovalChange(value, CHANGE_REASON))
                    capacity[clip] -= 1
                elif len(capacity) < 29:
                    api.add_clip(self.root, BATCH, clip, api.AddedClip('probe', value))
                    capacity[clip] = 3
                else:
                    return False
            except (BudgetAuthorityError, ValueError):
                return False
            return True
        for count in (1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1):
            while once(count):
                version += 1
        return len((self.root / AUTHORITY).read_bytes())

    def widest_completion(self, ref: ClaimRef) -> None:
        big = tuple({'path': '\U0001F600' * 85 + f'{index:04d}', 'sha256': f'{index:064x}', 'bytes': 10 ** 15}
                    for index in range(8))
        usage = {'inputTokens': 10 ** 15, 'outputTokens': 10 ** 15, 'cachedInputTokens': 10 ** 15,
                 'reasoningTokens': 10 ** 15}
        api.complete_task(self.root, BATCH, ref, TaskResult(big, usage))

    def end_director(self) -> None:
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))

    def test_a_launch_outcome_does_not_consume_task_settlement_room(self) -> None:
        budget = self.reserve(self.project, route='final', name='out-' + 'o' * 200)
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.start_task('critic', host_turn('critic'))
        self.end_director()
        size = self.fill()
        self.assertGreater(size, MAX_RECORD_BYTES - 2 * settlement.settlement_reserve(self.record()))
        stages = [{'phase': 'p' * 500, 'status': 's' * 500, 'elapsedSeconds': 1.5} for _ in range(80)]
        binding.record_request_outcome({'productionBudget': budget},
                                       {'status': 'native-short-checked-for-review', 'output': '/o/' + 'x' * 3000,
                                        'sha256': 'a' * 64, 'stages': stages})
        attempt = self.record()['clips']['A']['attempts'][-1]
        self.assertEqual((len(attempt['stages']), attempt['stages'][0]['phase']), (64, 'p' * 64))
        native_batch.cmd_status(ns(batch=BATCH))                   # read-only observation: never refused for room
        self.widest_completion(ref)
        self.assertEqual(self.state('critic'), 'completed')

    def test_superseding_settled_work_does_not_consume_task_settlement_room(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.start_task('critic', host_turn('critic'))
        self.enqueue(task_spec('root'), *[task_spec(f'd{index:03d}' + 'x' * 50, prerequisites=('root',))
                                          for index in range(200)])
        self.finish_task(self.start_task('root'), 'root')
        for index in range(200):
            self.finish_task(self.start_task(f'd{index:03d}' + 'x' * 50), f'd{index}')
        self.end_director()
        self.fill()
        api.supersede_task(self.root, BATCH, 'root', '\U0001F600' * 42)
        self.widest_completion(ref)
        self.assertEqual(self.state('critic'), 'completed')

    def test_status_still_works_at_the_reserve_boundary(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        self.start_task('critic', host_turn('critic'))
        self.fill()
        native_batch.cmd_status(ns(batch=BATCH))

    def test_ordinary_five_clip_batch_capacity(self) -> None:
        """Reviewer r3 probe: the room does not refuse ordinary 5-clip work early."""
        for clip in ('C', 'D', 'E'):
            api.add_clip(self.root, BATCH, clip, api.AddedClip('probe', approval(clip)))
        self.reserve(self.project, route='final', name='l0', options={'n': 0})
        self.reserve(self.project, route='preview', name='l1', options={'n': 1})
        count = 0
        while count < 255:
            self.enqueue(task_spec(f'c{count:03d}', 'check', clip_id='ABCDE'[count % 5]))
            count += 1
        self.assertEqual(len(self.record()['production']['tasks']), 256)      # the task bound, not the room

    def test_real_delivered_paths_fit(self) -> None:
        """Reviewer r3 probe: macOS paths of 1,021-1,024 UTF-8 bytes in any script are accepted."""
        for output in ('/' + '\U0001F600' * 255, '/' + '\u6f22' * 340, '/' + '\u00e9' * 511):
            settlement.launch_outcome({'status': 'native-short-checked-for-review', 'output': output}, ('x',))

    def test_a_delivered_path_is_refused_past_its_bound_never_cut(self) -> None:
        result = {'status': 'native-short-checked-for-review', 'output': '/o/' + 'é' * 1000, 'sha256': 'a' * 64}
        with self.assertRaisesRegex(ValueError, 'never cut'):
            settlement.launch_outcome(result, binding.SUCCESS)
        kept = settlement.launch_outcome({**result, 'output': '/o/out.mp4'}, binding.SUCCESS)
        self.assertEqual(kept['delivery']['output'], '/o/out.mp4')


if __name__ == '__main__':
    unittest.main()
