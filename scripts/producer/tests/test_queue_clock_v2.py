"""Short capacity clock v2 (P1 Step B1, M-044): the v2 shape, v1 clocks read-only, and the one schema step.

Private TEST records only: every authority root is a private temporary directory and no clock reads the host.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import FakeClock, fake_clock, private_root, task_spec
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import ClockAnchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_schema import SCHEMA_VERSION, _record_problem, validate_record
from studio.native_budget_store import canonical, read_batch
from studio.production import queue_authority, queue_clock
from studio.production import queue_clock_schema as schema
from studio.production.tasks import new_row

BATCH = 'clock-schema'
OWNER = {'pid': 7001, 'pgid': 7001, 'started': 'Sun Sep 27 10:00:00 2026'}
V1_ROW = {'state': 'waiting', 'resource': 'heavy-pool', 'evidence': '{}', 'seenElapsed': 300.0, 'taskId': None,
          'attemptId': None}
# The P0 engine's new_clock() output after 120 s of settled credit, with one waiting owner.
V1_CLOCK = {'policy': 'short-render-capacity-v1', 'excludedSeconds': 120.0, 'pendingSeconds': 0.0,
            'observedElapsed': 300.0, 'uncertainSeconds': 0.0, 'workers': {'/TEST/owner-a': V1_ROW},
            'taskCredits': {}, 'deliveryCredits': {}}
V2_ROW = {**V1_ROW, 'supervisor': OWNER, 'boot': 'TEST-boot', 'ticket': 7, 'occupants': ['a' * 32],
          'waitClass': 'capacity'}
CONTEXT = {'clipId': 'A', 'workerId': '/TEST/owner-b', 'supervisor': OWNER, 'boot': 'TEST-boot', 'taskId': None,
           'attemptId': None}
WORKING = {'state': 'working', 'resource': 'heavy-pool', 'evidence': 'admitted'}


def short_record(clock: dict | None = None) -> dict:
    """A TEST batch record with one Short, A, as this engine creates it; ``clock`` replaces A's clock."""
    anchor = ClockAnchor('TEST-boot', 5000.0, 1_800_000_000.0, 0.0)
    record = new_batch_record(BatchSpec(BATCH, ('A',), (), 1), anchor)
    if clock is not None:
        record['clips']['A']['capacityClock'] = copy.deepcopy(clock)
    return record


def add_tasks(record: dict) -> None:
    """A run-scoped check task and an author task for A, as ``tasks.new_row`` writes them."""
    for task_id, kind in (('check-1', 'check'), ('author-1', 'author')):
        record['production']['tasks'][task_id] = new_row(record, task_spec(task_id, kind, run_id=BATCH), [], (0, 0.0))


def write_raw(root: Path, record: dict) -> None:
    """Replace the batch's authority bytes (compatibility tests only)."""
    (root / 'batches' / BATCH / 'authority.json').write_bytes(canonical(record))


def full_v2_clock() -> dict:
    """A valid v2 clock with every new field set to a non-initial value."""
    clock = schema.new_clock()
    clock.update(excludedSeconds=120.0, observedElapsed=300.0, directorWorking=False,
                 workers={'/TEST/owner-a': copy.deepcopy(V2_ROW)},
                 occupancy={'fingerprint': 'c' * 64, 'sinceElapsed': 200.0},
                 stall={'state': 'cancelled', 'sinceElapsed': 250.0, 'occupants': ['a' * 32],
                        'decisions': [{'kind': 'cancel', 'reason': 'TEST operator reason', 'elapsed': 260.0}]},
                 orphans={'count': 3, 'recent': [{**V2_ROW, 'state': 'working', 'orphanedElapsed': 280.0}]},
                 checkpoint={'excludedSeconds': 100.0, 'elapsed': 250.0, 'count': 2},
                 handoff={'elapsed': 2000.0, 'countedSeconds': 1880.0, 'totalSeconds': 2000.0,
                          'deadlineElapsed': 2520.0, 'onTime': True})
    return clock


def _set(path: str, value: object) -> Callable[[dict], None]:
    """A mutation that sets one dotted path of the clock (list indexes as digits)."""
    def mutate(clock: dict) -> None:
        """Walk to the parent of the leaf and set it."""
        *parents, leaf = path.split('.')
        target = clock
        for key in parents:
            target = target[int(key)] if type(target) is list else target[key]
        target[int(leaf) if type(target) is list else leaf] = value
    return mutate


def _drop(key: str) -> Callable[[dict], object]:
    """A mutation that removes one top-level key."""
    return lambda clock: clock.pop(key)


STATE, POOL, ORPHAN_ROWS = 'Short capacity worker state', 'Short capacity worker pool evidence', \
    'Short capacity clock orphan rows'
SHAPE, STALL, DECISIONS = 'Short capacity clock shape/policy', 'Short capacity clock stall', \
    'Short capacity clock stall decisions: at most one, the operator\'s recorded cancel'
DECISION = {'kind': 'cancel', 'reason': 'TEST', 'elapsed': 1.0}
UNOWNED = {key: value for key, value in V2_ROW.items() if key not in ('supervisor', 'boot')}
VIOLATIONS = (
    ('no hand-off key', _drop('handoff'), SHAPE),
    ('an unknown key', _set('extra', 1), SHAPE),
    ('an unknown policy', _set('policy', 'short-render-capacity-v3'), SHAPE),
    ('v1 policy with v2 keys', _set('policy', 'short-render-capacity-v1'), SHAPE),
    ('directorWorking not a bool', _set('directorWorking', 'yes'), 'Short capacity clock director activity'),
    ('occupancy fingerprint not a digest', _set('occupancy.fingerprint', 'C' * 64), 'Short capacity clock occupancy'),
    ('occupancy time negative', _set('occupancy.sinceElapsed', -1.0), 'Short capacity clock occupancy'),
    ('occupancy extra key', _set('occupancy.extra', None), 'Short capacity clock occupancy'),
    ('dropped stall state waiting-kept', _set('stall.state', 'waiting-kept'), STALL),
    ('stall time not finite', _set('stall.sinceElapsed', float('nan')), STALL),
    ('nine stall occupants', _set('stall.occupants', ['x'] * 9), STALL),
    ('a 65-character stall occupant', _set('stall.occupants', ['x' * 65]), STALL),
    ('2 decisions refused', _set('stall.decisions', [DECISION, DECISION]), DECISIONS),
    ('dropped decision keep-waiting', _set('stall.decisions', [{**DECISION, 'kind': 'keep-waiting'}]), DECISIONS),
    ('a 516-byte decision reason', _set('stall.decisions.0.reason', 'é' * 86), DECISIONS),
    ('a decision without its time', _set('stall.decisions', [{'kind': 'cancel', 'reason': 'TEST'}]), DECISIONS),
    ('orphan count below its rows', _set('orphans.count', 0), 'Short capacity clock orphans'),
    ('orphan count a bool', _set('orphans.count', True), 'Short capacity clock orphans'),
    ('seventeen orphan rows', _set('orphans', {'count': 17, 'recent': [
        {**V2_ROW, 'orphanedElapsed': 1.0}] * 17}), 'Short capacity clock orphans'),
    ('an orphan row without its time', _set('orphans.recent', [dict(V2_ROW)]), ORPHAN_ROWS),
    ('an orphan row without its owner', _set('orphans.recent', [{**UNOWNED, 'orphanedElapsed': 1.0}]), ORPHAN_ROWS),
    ('33 checkpoints', _set('checkpoint.count', 33), 'Short capacity clock checkpoint'),
    ('checkpoint time not a number', _set('checkpoint.elapsed', '250'), 'Short capacity clock checkpoint'),
    ('hand-off onTime not a bool', _set('handoff.onTime', 1), 'Short capacity clock hand-off'),
    ('hand-off counted time negative', _set('handoff.countedSeconds', -1.0), 'Short capacity clock hand-off'),
    ('hand-off without its deadline', _set('handoff', {'elapsed': 1.0, 'countedSeconds': 1.0, 'totalSeconds': 1.0,
                                                       'onTime': True}), 'Short capacity clock hand-off'),
    ('a v2 row without its ticket', lambda clock: clock['workers']['/TEST/owner-a'].pop('ticket'), STATE),
    ('a v2 row without its owner identity', lambda clock: clock['workers']['/TEST/owner-a'].pop('boot'), STATE),
    ('a v2 row in an unknown state', _set('workers./TEST/owner-a.state', 'finished'), STATE),
    ('a negative ticket', _set('workers./TEST/owner-a.ticket', -1), POOL),
    ('a boolean ticket', _set('workers./TEST/owner-a.ticket', True), POOL),
    ('nine row occupants', _set('workers./TEST/owner-a.occupants', ['x'] * 9), POOL),
    ('an unknown wait class', _set('workers./TEST/owner-a.waitClass', 'queue'), POOL),
)


class SchemaTests(unittest.TestCase):
    """The v2 clock is written once, validated closed, and a v1 clock is read but never advanced."""

    def setUp(self) -> None:
        """No test reads the host's clocks."""
        self.enterContext(fake_clock(FakeClock()))

    def test_new_clock_is_v2(self) -> None:
        """Every v2 key is present with the value of a Short that has recorded nothing; new Shorts get it."""
        self.assertEqual(schema.new_clock(), {
            'policy': 'short-render-capacity-v2', 'excludedSeconds': 0.0, 'pendingSeconds': 0.0,
            'observedElapsed': 0.0, 'uncertainSeconds': 0.0, 'workers': {}, 'taskCredits': {}, 'deliveryCredits': {},
            'directorWorking': True, 'occupancy': {'fingerprint': None, 'sinceElapsed': 0.0},
            'stall': {'state': None, 'sinceElapsed': None, 'occupants': [], 'decisions': []},
            'orphans': {'count': 0, 'recent': []},
            'checkpoint': {'excludedSeconds': 0.0, 'elapsed': 0.0, 'count': 0}, 'handoff': None})
        self.assertEqual((schema.POLICIES, schema.MAX_WORKERS, schema.MAX_OCCUPANTS, schema.MAX_ORPHAN_ROWS,
                          schema.MAX_CHECKPOINTS, schema.WORKER_STATES, schema.STALL_STATES),
                         (('short-render-capacity-v1', 'short-render-capacity-v2'), 64, 8, 16, 32,
                          ('working', 'waiting', 'unverified'), (None, 'capacity-stalled', 'cancelled')))
        self.assertFalse(hasattr(schema, 'MAX_STALL_DECISIONS'))   # X35(g): one decision kind, one row
        self.assertIs(queue_clock.new_clock, schema.new_clock)
        self.assertIs(queue_clock.problem, schema.problem)
        record = short_record()
        clip = record['clips']['A']
        self.assertEqual(clip['capacityClock'], schema.new_clock())
        validate_record(record)
        self.assertTrue(queue_clock.enabled(clip) and queue_clock.writable(clip))
        self.assertIsNone(schema.problem({**clip, 'capacityClock': full_v2_clock()}))

    def test_v1_clock_stays_readable_and_read_only(self) -> None:
        """A P0 v1 clock validates and keeps its 120 s; checkpoint and observe_worker leave it byte-identical."""
        record = short_record(V1_CLOCK)
        clip = record['clips']['A']
        validate_record(record)
        self.assertIsNone(queue_clock.problem(clip))
        self.assertEqual(queue_clock.excluded(clip), 120.0)
        self.assertTrue(queue_clock.enabled(clip))
        self.assertFalse(queue_clock.writable(clip))
        before = canonical(clip)
        queue_clock.checkpoint(record, 303.0)
        self.assertEqual(queue_clock.observe_worker(record, CONTEXT, WORKING, 303.0), 120.0)
        finished = {**WORKING, 'state': 'finished'}
        self.assertEqual(queue_clock.observe_worker(record, {**CONTEXT, 'workerId': '/TEST/owner-a'}, finished, 304.0),
                         120.0)
        self.assertEqual(canonical(clip), before)
        self.assertEqual(queue_clock.status(clip, 400.0)['excludedRenderQueueSeconds'], 120.0)
        self.assertEqual(queue_clock.problem({**clip, 'capacityClock': {**V1_CLOCK, 'workers': {
            '/TEST/owner-a': {**V1_ROW, 'state': 'unverified'}}}}), STATE)   # 'unverified' is a v2 state only
        v2 = short_record({**schema.new_clock(), 'observedElapsed': 300.0,
                           'workers': {'/TEST/owner-a': {**V2_ROW, 'waitClass': None}}})
        queue_clock.checkpoint(v2, 303.0)   # control: the same interval does advance a v2 clock
        self.assertEqual(v2['clips']['A']['capacityClock']['pendingSeconds'], 3.0)
        queue_clock.observe_worker(v2, CONTEXT, WORKING, 303.0)
        self.assertEqual(v2['clips']['A']['capacityClock']['workers']['/TEST/owner-b'],
                         {**WORKING, 'supervisor': OWNER, 'boot': 'TEST-boot', 'seenElapsed': 303.0, 'taskId': None,
                          'attemptId': None, 'ticket': None, 'occupants': [], 'waitClass': None})
        validate_record(v2)

    def test_v2_field_violations_are_refused(self) -> None:
        """Each new field is refused by name when its type, bound or state is wrong."""
        clip = short_record()['clips']['A']
        for name, mutate, message in VIOLATIONS:
            with self.subTest(name):
                clock = full_v2_clock()
                mutate(clock)
                self.assertEqual(schema.problem({**clip, 'capacityClock': clock}), message)
        record = short_record(full_v2_clock())
        record['clips']['A']['capacityClock']['stall']['decisions'] *= 2
        with self.assertRaisesRegex(ValueError, 'budget record is invalid: Short capacity clock stall decisions'):
            validate_record(record)
        unverified = full_v2_clock()
        unverified['workers']['/TEST/owner-a']['state'] = 'unverified'
        self.assertIsNone(schema.problem({**clip, 'capacityClock': unverified}))

    def test_v7_record_lifts_unchanged(self) -> None:
        """A v7 record (v1 clock, task rows) reads as the new version with every clip and task byte-equal."""
        root = private_root(self)
        record = short_record(V1_CLOCK)
        add_tasks(record)
        create_batch(root, record)
        v7 = {**copy.deepcopy(record), 'schemaVersion': 7}
        write_raw(root, v7)
        lifted = read_batch(root, BATCH)
        self.assertEqual(lifted['schemaVersion'], SCHEMA_VERSION)
        self.assertEqual(canonical({**lifted, 'schemaVersion': 7}), canonical(v7))
        self.assertEqual(lifted['clips']['A']['capacityClock']['policy'], 'short-render-capacity-v1')
        self.assertEqual(set(lifted['production']['tasks']), {'check-1', 'author-1'})

    def test_new_version_record_refused_by_version_in_old_reader(self) -> None:
        """The P0 engine reads (5, 6, 7) only, so it refuses a new record by version, never as corrupt."""
        self.assertEqual(SCHEMA_VERSION, 8)
        self.assertNotIn(SCHEMA_VERSION, (5, 6, 7))
        self.assertEqual(_record_problem({'schemaVersion': 99}),
                         'written by another engine version (schemaVersion 99, this engine 8); finish it with that '
                         'engine, or archive it once it is closed or its delivery deadline has passed')
        for version in (5, 6, 7, 8):
            with self.subTest(version=version):
                self.assertEqual(_record_problem({'schemaVersion': version}), 'unexpected fields')


class AuthorityBindingTests(unittest.TestCase):
    """``queue_authority`` at M-044 (W2-D7): only a v2 clock is bound to a grant or to supporting work."""

    def setUp(self) -> None:
        """No test reads the host's clocks."""
        self.enterContext(fake_clock(FakeClock()))

    def test_only_a_v2_clock_is_bound_to_a_grant(self) -> None:
        """A v1 clock's grant carries no credit reference; a v2 reference names the v2 policy and its baseline."""
        grant, context = {'grantedSeconds': 900.0}, {'authority': '/TEST/budgets', 'batchId': BATCH, 'clipId': 'A'}
        self.assertIs(queue_authority.bind_allocation(grant, short_record(V1_CLOCK), context), grant)
        v2 = short_record({**schema.new_clock(), 'excludedSeconds': 30.0, 'observedElapsed': 60.0})
        reference = queue_authority.bind_allocation(grant, v2, context)['capacityCredit']
        self.assertEqual(reference, {**context, 'policy': 'short-render-capacity-v2', 'atGrant': 30.0})
        queue_authority.validate_reference(reference)
        for bad in ({'policy': 'short-render-capacity-v1'}, {'atGrant': -1.0}, {'atGrant': True}):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, 'Malformed capacity-credit allocation'):
                queue_authority.validate_reference({**reference, **bad})

    def test_supporting_work_is_bound_only_to_v2_clocks(self) -> None:
        """A utility owner serving a v1 Short and a v2 Short records observations for the v2 one only."""
        record = short_record(V1_CLOCK)
        record['clips']['B'] = {**copy.deepcopy(record['clips']['A']), 'capacityClock': schema.new_clock()}
        bindings = {f'/TEST/{clip}': {'status': 'active', 'batchId': BATCH, 'clipId': clip} for clip in 'AB'}
        primary = {'batchId': 'other-batch', 'clipId': 'Z', 'supervisor': OWNER, 'boot': 'TEST-boot'}
        with mock.patch('studio.native_budget_owner.served_projects', return_value=sorted(bindings)), \
                mock.patch('studio.native_budget_registry.owner_binding', side_effect=lambda _, key: bindings[key]), \
                mock.patch('studio.native_budget_store.read_batch', return_value=record):
            contexts = queue_authority.supporting_contexts(SimpleNamespace(path=Path('/TEST/owner')), primary)
        self.assertEqual([(row['clipId'], row['supervisor'], row['boot']) for row in contexts],
                         [('B', OWNER, 'TEST-boot')])


if __name__ == '__main__':
    unittest.main()
