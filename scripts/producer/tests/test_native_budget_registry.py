"""Registry and lifecycle regressions: stray entries, interrupted starts, copies, revisions, owners."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import ENGINE, make_project
from _dispatch_fixture import added_approval
from test_native_budget_authority import AuthorityCase
import native_batch
from studio import native_budget_batches as batches
from studio import native_budget_binding as binding
from studio import native_budget_exporter as exporter
from studio import native_budget_owner as owner_budget
from studio import native_budget_registry as registry
from studio import native_budget_store as store
from studio.native_budget_store import BudgetAuthorityError


def ns(**values: object) -> argparse.Namespace:
    return argparse.Namespace(**values)


class RegistryCase(AuthorityCase):
    """AuthorityCase plus the coordinator CLI pointed at the same private root."""

    def setUp(self) -> None:
        super().setUp()
        from studio import native_budget_engine
        patch = mock.patch.object(native_budget_engine, 'engine_identity', return_value=dict(ENGINE))
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(owner_budget, 'default_root', return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def fail_launch(self, project: Path, name: str, options: dict) -> None:
        self.close(self.reserve(project, name=name, options=options))

    def exhaust(self, project: Path) -> None:
        self.fail_launch(project, 'a1', {'n': 1})
        self.fail_launch(project, 'a2', {'n': 2})

    def close_batch(self) -> None:
        self.clock.advance(2400)
        native_batch.cmd_close(ns(batch='batch-auth'))

    def unrelated(self, name: str = 'unrelated') -> Path:
        return make_project(self.work, name, source=b'another-recording')


class StrayEntryTests(RegistryCase):
    """Finder files and interrupted starts never lock the host; junk is named."""

    def test_hidden_entries_are_ignored(self) -> None:
        (self.root / 'batches/.DS_Store').write_bytes(b'\0\0\0\1Bud1')
        self.assertEqual(self.reserve(self.project)['clipId'], 'A')

    def test_visible_junk_is_named(self) -> None:
        (self.root / 'batches/Notes.txt').write_text('x')
        with self.assertRaisesRegex(BudgetAuthorityError, 'Notes.txt'):
            self.reserve(self.project)

    def test_interrupted_start_leaves_nothing_resolution_reads(self) -> None:
        self.close_batch()
        with mock.patch.object(store.BatchSession, 'commit', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.start('half-made', ('A',))
        self.assertNotIn('half-made', batches.list_batches(self.root))
        self.assertIsNone(registry.resolve_binding(self.root, self.unrelated()))
        self.start('half-made', ('A',))
        self.assertIn('half-made', batches.list_batches(self.root))


class CorruptAuthorityTests(RegistryCase):
    """Nested rows and policy copies are part of the closed schema."""

    def edit_file(self, change: object) -> None:
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        change(record)
        path.write_text(json.dumps(record))

    def test_malformed_nested_row_refuses_cleanly(self) -> None:
        self.edit_file(lambda record: record['clips']['A']['projects'].append('/old/format/native-v1'))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            admitted = exporter.reserve_for_args(ns(project=self.unrelated(), output=self.work / 'o', preview_only=True))
        self.assertEqual(admitted, (False, None))
        self.assertIn('refused-by-production-budget', out.getvalue())

    def test_raised_limit_or_deadline_is_corrupt(self) -> None:
        for field, key, value in (('limits', 'exportAttempt', 9), ('deadlines', 'deliverySeconds', 99999)):
            original = json.loads((self.root / 'batches/batch-auth/authority.json').read_text())[field][key]
            self.edit_file(lambda record: record[field].update({key: value}))
            with self.assertRaisesRegex(BudgetAuthorityError, 'policy'):
                self.reserve(self.project)
            self.edit_file(lambda record: record[field].update({key: original}))

    def test_two_active_batches_are_corrupt(self) -> None:
        self.close_batch()
        self.start('batch-next', ('A',))
        self.edit_file(lambda record: record.update(status='active', closedAtElapsed=None))
        with self.assertRaisesRegex(BudgetAuthorityError, 'only one may be'):
            registry.resolve_binding(self.root, self.project)


class BindingTests(RegistryCase):
    """Copies, revisions and concurrent coordinators cannot open fresh counters."""

    def test_revision_under_an_added_clip_is_refused(self) -> None:
        self.exhaust(self.project)
        native_batch.cmd_add_clip(ns(batch='batch-auth', clip='A-retry', reason='retry',
                                     approval=added_approval(self.work, 'A-retry')))
        revision = make_project(self.work, 'native-v2', cuts=((12.0, 40.0), (50.0, 78.0)))
        with self.assertRaisesRegex(registry.BudgetRefused, 're-cuts clip A'):
            binding.bind_project(self.root, 'batch-auth', 'A-retry', revision)
        different = make_project(self.work, 'another-short', cuts=((200.0, 240.0),))
        binding.bind_project(self.root, 'batch-auth', 'A-retry', different)

    def test_a_short_from_another_recording_binds(self) -> None:
        other = self.unrelated()
        binding.bind_project(self.root, 'batch-auth', 'B', other)
        self.assertEqual(self.reserve(other)['clipId'], 'B')

    def test_distinct_real_shorts_sharing_seconds_stay_independent(self) -> None:
        clip_c = make_project(self.work, 'C', cuts=((0.0, 18.4),))
        clip_d = make_project(self.work, 'D', cuts=((6.6, 50.2),))  # 11.8 s in common: 23.5% of the union
        binding.bind_project(self.root, 'batch-auth', 'B', clip_c)
        native_batch.cmd_add_clip(ns(batch='batch-auth', clip='D', reason='fourth Short',
                                     approval=added_approval(self.work, 'D')))
        binding.bind_project(self.root, 'batch-auth', 'D', clip_d)
        with self.assertRaisesRegex(registry.BudgetRefused, 're-cuts clip B'):
            binding.bind_project(self.root, 'batch-auth', 'D', make_project(self.work, 'C-v2', cuts=((0.0, 18.0),)))

    def test_concurrent_binds_of_one_folder_bind_once(self) -> None:
        project = make_project(self.work, 'contested', cuts=((300.0, 330.0),))
        outcomes, barrier = [], threading.Barrier(2)

        def bind(clip: str) -> None:
            barrier.wait(timeout=10)
            try:
                binding.bind_project(self.root, 'batch-auth', clip, project)
                outcomes.append('bound')
            except registry.BudgetRefused as error:
                outcomes.append(str(error))
        threads = [threading.Thread(target=bind, args=(clip,)) for clip in ('A', 'B')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(outcomes.count('bound'), 1)
        self.assertIn('already belongs to clip', next(item for item in outcomes if item != 'bound'))

    def test_copy_in_a_new_batch_is_explicit_new_work(self) -> None:
        self.exhaust(self.project)
        self.close_batch()
        copy = self.work / 'copy'
        shutil.copytree(self.project, copy)
        with self.assertRaisesRegex(registry.BudgetRefused, 'closed batch batch-auth'):
            self.reserve(copy)
        self.start('batch-next', ('A',))
        binding.bind_project(self.root, 'batch-next', 'A', copy)
        self.assertEqual(self.reserve(copy)['batchId'], 'batch-next')


class ClosedBatchTests(RegistryCase):
    """A closed batch keeps its Shorts, not every Short from the same recording."""

    def test_other_selection_from_the_same_recording_is_unbudgeted(self) -> None:
        self.close_batch()
        other = make_project(self.work, 'next-month', cuts=((400.0, 460.0),))
        self.assertIsNone(registry.resolve_binding(self.root, other))
        revision = make_project(self.work, 'native-v2')
        with self.assertRaisesRegex(registry.BudgetRefused, 'clip A of closed batch batch-auth'):
            registry.resolve_binding(self.root, revision)

    def test_archive_is_the_explicit_release_and_keeps_history(self) -> None:
        attempt = self.work / 'old-attempt'
        attempt.mkdir()
        budget = self.reserve(self.project, name='old-attempt')
        self.close(budget)
        (attempt / 'export-request.json').write_text(json.dumps({'project': str(self.project),
                                                                 'productionBudget': budget}))
        with self.assertRaisesRegex(registry.BudgetRefused, 'closed batch'):
            native_batch.cmd_archive(ns(batch='batch-auth', reason='operator released it'))
        self.close_batch()
        native_batch.cmd_archive(ns(batch='batch-auth', reason='operator released it'))
        self.assertTrue((self.root / 'archive/batch-auth/authority.json').is_file())
        self.assertIsNone(registry.resolve_binding(self.root, self.project))
        request = {'project': str(self.project), 'output': str(self.work / 'next'), 'runtime': str(self.work / 'rt/x')}
        with mock.patch('studio.native_export_history.candidate_attempts', return_value=[attempt]):
            binding.require_budget_continuity(request)

    def test_live_batch_cap_asks_for_archiving(self) -> None:
        self.close_batch()
        with mock.patch.object(batches, 'MAX_BATCHES', 1):
            with self.assertRaisesRegex(registry.BudgetRefused, 'archive closed ones'):
                self.start('batch-next', ('A',))
            native_batch.cmd_archive(ns(batch='batch-auth', reason='operator released it'))
            self.start('batch-next', ('A',))


class TrailTests(RegistryCase):
    """A full trail refuses new work but never keeps a batch open; failed writes are marked."""

    def test_full_trail_still_closes(self) -> None:
        with (self.root / 'batches/batch-auth/events.jsonl').open('ab') as handle:
            handle.truncate(store.MAX_EVENT_BYTES - 10)
        with self.assertRaisesRegex(BudgetAuthorityError, 'trail is full'):
            self.reserve(self.project)
        self.close_batch()
        self.assertEqual(self.record()['status'], 'closed')
        self.assertIsNone(registry.resolve_binding(self.root, self.unrelated()))

    def test_failed_record_write_is_marked(self) -> None:
        with mock.patch.object(store, 'write_pending_replace', side_effect=OSError('disk full')):
            with self.assertRaises(BudgetAuthorityError):
                self.reserve(self.project)
        trail = [json.loads(line) for line in
                 (self.root / 'batches/batch-auth/events.jsonl').read_text().splitlines()]
        self.assertEqual([row['event'] for row in trail[-2:]], ['launch-admitted', 'commit-failed'])
        self.assertEqual(self.record()['clips']['A']['attempts'], [])


class IdentityTests(RegistryCase):
    """Copies of the same evidence and fresh cache folders are the same launch."""

    def test_copied_evidence_is_an_unchanged_retry(self) -> None:
        (self.work / 'reviews.json').write_text('{"r": 1}')
        shutil.copyfile(self.work / 'reviews.json', self.work / 'reviews-copy.json')
        plain = exporter.launch_options(ns(preview_reviews=self.work / 'reviews.json'))
        copy = exporter.launch_options(ns(preview_reviews=self.work / 'reviews-copy.json'))
        self.assertEqual(plain, copy)
        self.fail_launch(self.project, 'a1', plain)
        with self.assertRaisesRegex(registry.BudgetRefused, 'Unchanged deterministic failure'):
            self.reserve(self.project, name='a2', options=copy)

    def test_cache_folder_is_not_an_input(self) -> None:
        (self.work / 'c1').mkdir()
        self.assertEqual(exporter.launch_options(ns(cache=self.work / 'c1')), {})


class OwnerScopeTests(RegistryCase):
    """Owners budget exactly the bound clips they serve and never refuse unbudgeted work."""

    def owner(self, project: Path, serves: tuple | None) -> SimpleNamespace:
        return SimpleNamespace(hard_deadline=None, project=project, label='test', deadline=600,
                               settings=SimpleNamespace(serves=serves))

    def test_unbudgeted_request_owners_are_never_refused(self) -> None:
        in_flight = self.owner(self.unrelated('admitted-before-start'), ())
        owner_budget.apply_budget_to_owner(in_flight)
        self.assertIsNone(in_flight.hard_deadline)
        unbound = self.owner(self.unrelated('unbound'), None)
        owner_budget.apply_budget_to_owner(unbound)
        self.assertIsNone(unbound.hard_deadline)

    def test_supporting_owner_serving_a_bound_clip_inherits_the_deadline(self) -> None:
        owner_input = self.work / 'bundle/owner-input'
        owner_input.mkdir(parents=True)
        self.clock.advance(2000)
        supporting = self.owner(owner_input, (self.project,))
        owner_budget.apply_budget_to_owner(supporting)
        self.assertIsNotNone(supporting.hard_deadline)
        self.assertAlmostEqual(supporting.deadline, 2400 - 120 - 2000 - 45, places=3)

    def test_supporting_owner_after_handoff_is_refused(self) -> None:
        self.mutate('batch-auth', lambda record: record['clips']['A'].update(state='handed-off'))
        with self.assertRaisesRegex(registry.BudgetRefused, 'handed off'):
            owner_budget.apply_budget_to_owner(self.owner(self.project, None))



class DrainingRegistryTests(RegistryCase):
    """A draining batch is still the current batch; supporting compute cannot outlive its batch."""

    def drain_file(self) -> None:
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record.update(status='draining', closedAtElapsed=None)
        record['production']['drain'] = {'startedElapsed': 2400.0, 'reason': 'TEST'}
        path.write_text(json.dumps(record))

    def test_a_draining_and_an_active_batch_are_corrupt_together(self) -> None:
        self.close_batch()
        self.start('batch-next', ('A',))
        self.drain_file()
        with self.assertRaisesRegex(BudgetAuthorityError, 'active or draining; only one may be'):
            registry.resolve_binding(self.root, self.project)

    def test_supporting_owners_of_a_draining_or_closed_batch_are_refused_until_archive(self) -> None:
        owner = SimpleNamespace(hard_deadline=None, project=self.project, label='audio', deadline=600,
                                settings=SimpleNamespace(serves=None))
        self.drain_file()
        with self.assertRaisesRegex(registry.BudgetRefused, 'belongs to draining batch batch-auth'):
            owner_budget.apply_budget_to_owner(owner)
        self.mutate('batch-auth', lambda record: record.update(status='closed', closedAtElapsed=2500.0))
        with self.assertRaisesRegex(registry.BudgetRefused, 'belongs to closed batch batch-auth'):
            owner_budget.apply_budget_to_owner(owner)
        native_batch.cmd_archive(ns(batch='batch-auth', reason='operator released it'))
        owner_budget.apply_budget_to_owner(owner)
        self.assertIsNone(owner.hard_deadline)

    def test_new_work_stops_at_the_reserve_and_settlement_still_writes(self) -> None:
        trail = self.root / 'batches/batch-auth/events.jsonl'
        with trail.open('ab') as handle:
            handle.truncate(store.MAX_EVENT_BYTES - store.TERMINAL_RESERVE_BYTES - 10)
        with self.assertRaisesRegex(BudgetAuthorityError, 'trail is full'):
            self.reserve(self.project)
        self.close_batch()
        self.assertEqual(self.record()['status'], 'closed')
        self.assertLess(trail.stat().st_size, store.MAX_EVENT_BYTES)


class FormatIdentityTests(RegistryCase):
    """Format is part of identity (unit D1): Long manifests and lineage, never the Short selection."""

    def test_a_folder_declares_exactly_one_plan(self) -> None:
        from _budget_fixture import make_long_project
        both = make_long_project(self.work, 'both-plans')
        (both / 'SHORT-PROJECT.json').write_text((self.project / 'SHORT-PROJECT.json').read_text())
        with self.assertRaisesRegex(registry.BudgetRefused, 'exactly one SHORT-PROJECT.json or LONG-PROJECT.json'):
            registry.project_identity(both)

    def test_a_long_project_never_binds_to_a_short(self) -> None:
        from _budget_fixture import make_long_project
        with self.assertRaisesRegex(registry.BudgetRefused, 'Output B is a short; this project is a long'):
            binding.bind_project(self.root, 'batch-auth', 'B', make_long_project(self.work, 'long-v1'))

    def test_a_closed_batch_keeps_refusing_its_long_and_revisions_of_it(self) -> None:
        from _budget_fixture import RECORDINGS, make_long_project
        from studio.production import api
        from studio.production.outputs import OutputAuthorization
        with mock.patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1):
            api.authorize_output(self.root, 'batch-auth', OutputAuthorization('L', 'long', 'TEST Long', 'TEST operator',
                                                                              output_seconds=600.0))
        binding.bind_project(self.root, 'batch-auth', 'L', make_long_project(self.work, 'long-v1'))
        self.clock.advance(10800)
        native_batch.cmd_close(ns(batch='batch-auth'))
        revision = make_long_project(self.work, 'long-v2', RECORDINGS + (b'long-recording-d',), request='request-2')
        with self.assertRaisesRegex(registry.BudgetRefused, 'clip L of closed batch batch-auth'):
            registry.resolve_binding(self.root, revision)
        other = make_long_project(self.work, 'other-long', (b'other-x',), request='request-3')
        self.assertIsNone(registry.resolve_binding(self.root, other))


if __name__ == '__main__':
    unittest.main()
