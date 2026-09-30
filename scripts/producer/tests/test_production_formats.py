"""Format identity and policy (unit D1): Shorts and Longs under one run anchor, each on its own clock.

Authority tests use real private files and kernel locks under a temporary root (``RegistryCase``);
forecast tests use in-memory records. Every project, recording and handle is a TEST fixture.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import unittest
from unittest import mock

from _budget_fixture import (
    DIRECTOR, FINGERPRINT, RECORDINGS, FakeClock, approval, fake_clock, host_turn, make_long_project, make_project,
    source_sha, table, task_spec,
)
from _budget_fixture import b3_stand_in, handoff_confirmation, test_mp4  # P0 adapt
from test_native_budget_registry import RegistryCase, ns
import native_batch
from studio import native_budget_batches as batches
from studio import native_budget_binding as binding
from studio import native_budget_forecast as forecast
from studio import native_budget_launch as launch
from studio import native_budget_registry as registry
from studio import native_budget_schema as schema
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_report import batch_status
from studio.native_budget_selection import same_short
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api, formats
from studio.production.claims import ClaimRef, Enrollment
from studio.production.lineage import long_identity, output_match, same_long
from studio.production.mixed_forecast import mixed_status
from studio.production.outputs import OutputAuthorization, authorize_output
from studio.production.tasks import TaskConflict, TaskRefused

ALIVE = {'pid': 4242, 'pgid': 4242, 'started': 'Sun Sep 27 09:00:00 2026'}


def long_request(clip: str = 'L', seconds: float = 600.0) -> OutputAuthorization:
    """A TEST Long authorization."""
    return OutputAuthorization(clip, 'long', f'TEST Long {clip}', 'TEST operator', output_seconds=seconds)


def short_request(clip: str, **values: object) -> OutputAuthorization:
    """A TEST own-clock Short authorization with its approved title and script."""
    return OutputAuthorization(clip, 'short', f'TEST Short {clip}', 'TEST operator',
                               approval=values.pop('approval', None) or approval(clip), **values)


def historical_shorts() -> object:
    """P0 adapt (M-030): these A12 cases keep a Short's wall-clock forecast, the rule src keeps for historical
    Shorts. A capacity-clock Short's forecast counts its work without its queue wait (native_budget_forecast.py:191-192,
    mixed_forecast.py:122-123 and 277-287; shorts-completion STATUS.md rows 7 and 10, line 18), so it is never
    refused for waiting behind a Long. Whether that mix may still be refused is M7, owned by P1 (HANDOVER-P1.md)."""
    return mock.patch('studio.production.queue_clock.enabled', return_value=False)


class PolicyTests(unittest.TestCase):
    """The Short policy is today's; the Long policy is its own, with its evidence."""

    def test_the_short_policy_is_unchanged_and_the_long_policy_names_its_numbers(self) -> None:
        self.assertEqual((schema.DEADLINES['preparationSeconds'], schema.DEADLINES['deliverySeconds']), (1500, 2400))
        long = formats.LONG_POLICY
        self.assertEqual((long['deliverySeconds'], long['maxOutputSeconds'], long['routes']),
                         (10800, 900, ['preview', 'final', 'resume']))
        self.assertEqual(long['limits'], schema.LIMITS)          # the owner's per-output limits; no Long evidence
        ten, fifteen = formats.long_demand(600), formats.long_demand(900)
        self.assertEqual((ten['previewSeconds'], ten['finalSeconds'], ten['handoffReserveSeconds']),
                         (2440.0, 2275.0, 1620.0))
        self.assertEqual((fifteen['previewSeconds'], fifteen['finalSeconds'], fifteen['handoffReserveSeconds']),
                         (3610.0, 3362.5, 1920.0))
        self.assertIn('no measurement', ten['evidence'])
        self.assertIn('technical fixture only', fifteen['evidence'])
        self.assertIn('TREVOR_LONG_FORM_PRODUCTION_AUDIT_2026-09-16.md, lines 3 and 36-45', long['rates']['source'])
        self.assertIn('0.222-0.242 s per frame', fifteen['risks']['denseGraphics'])

    def test_a_long_preview_is_forecast_from_its_packet_windows_when_given(self) -> None:
        bound, packet = formats.long_demand(900), formats.long_demand(900, 12.0)   # default 3 x 120 frames at 30 fps
        self.assertEqual((bound['previewBasis'], bound['previewSeconds']),
                         ('whole-program bound (no preview packet yet)', 3610.0))
        self.assertEqual((packet['previewBasis'], packet['previewSeconds']), ('preview packet windows (12.0 s)', 391.0))
        with self.assertRaisesRegex(ValueError, 'within the program'):
            formats.long_demand(600, 601.0)

    def test_a_long_is_forecast_at_its_own_duration_never_at_fifteen_minutes(self) -> None:
        # An 11:10 (670 s) cut, the length of an earlier edit of the chosen qualification source.
        demand = formats.long_demand(670.0)
        self.assertEqual((demand['finalSeconds'], demand['previewSeconds'], demand['handoffReserveSeconds']),
                         (2528.75, 2713.0, 1690.0))
        self.assertEqual(formats.expected_deadlines('long', 0.0, 670.0), (6581.25, 10800.0))
        self.assertEqual(formats.long_demand(670.0, 12.0)['previewSeconds'], 327.75)
        self.assertIn('no measurement at this duration', demand['evidence'])

    def test_a_final_ending_at_its_grant_end_leaves_the_whole_hand_off_before_minute_180(self) -> None:
        reserve = formats.LONG_POLICY['handoffReserve']
        for seconds in (600.0, 660.0, 900.0):
            preparation, delivery = formats.expected_deadlines('long', 0.0, seconds)
            deadlines = {'deliverySeconds': delivery, 'handoffReserveSeconds': formats.long_handoff_seconds(seconds)}
            starts = formats.long_latest_starts(deadlines, seconds)
            parts = seconds * reserve['playbackPerOutputSecond'] + reserve['reviewNotesSeconds'] \
                + reserve['openConfirmSeconds']
            self.assertEqual(starts['latestFinalStart'], preparation)
            self.assertEqual(starts['grantEnd'] + parts + reserve['marginSeconds'], delivery)
        self.assertEqual((formats.long_handoff_seconds(660.0), formats.long_handoff_seconds(900.0)), (1680.0, 1920.0))

    def test_each_output_has_its_own_deadlines_under_the_run_anchor(self) -> None:
        self.assertEqual(formats.expected_deadlines('long', 0.0, 900.0), (5517.5, 10800.0))
        self.assertEqual(formats.expected_deadlines('long', 1800.0, 600.0), (8705.0, 12600.0))
        self.assertEqual(formats.expected_deadlines('short', 1800.0, None), (3300.0, 4200.0))


class FormatCase(RegistryCase):
    """A running batch (Shorts A and B on the batch clock, project native-v1 bound to A) and one heavy slot."""

    def setUp(self) -> None:
        super().setUp()
        patch = mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1)
        patch.start()
        self.addCleanup(patch.stop)

    def authorize(self, clip: str = 'L', fmt: str = 'long', **values: object) -> dict:
        request = long_request(clip, values.pop('seconds', 600.0)) if fmt == 'long' else short_request(clip, **values)
        return api.authorize_output(self.root, 'batch-auth', request)

    def raw(self) -> dict:
        return json.loads((self.root / 'batches/batch-auth/authority.json').read_text())

    def write_raw(self, change: object) -> None:
        record = self.raw()
        change(record)
        (self.root / 'batches/batch-auth/authority.json').write_text(json.dumps(record))

    def bind(self, clip: str, project: object) -> None:
        binding.bind_project(self.root, 'batch-auth', clip, project)

    def director(self) -> dict:
        return api.enroll_director(self.root, 'batch-auth', Enrollment('director', DIRECTOR, 'v1', FINGERPRINT))

    def running(self, task_id: str) -> ClaimRef:
        claimed = api.claim_task(self.root, 'batch-auth', task_id, host_turn(task_id))
        ref = ClaimRef(task_id, claimed['epoch'], claimed['token'])
        api.attach_task(self.root, 'batch-auth', ref, host_turn(task_id))
        return ref


class VersionTests(FormatCase):
    """Schema 4 was pre-release and is refused by version; other engines read a Long run's own deadline."""

    def test_a_pre_release_schema_4_record_is_refused_by_version_never_as_corrupt(self) -> None:
        self.authorize('L')                                      # even with a version-5-only output row
        self.write_raw(lambda record: record.update(schemaVersion=4))
        with self.assertRaisesRegex(BudgetAuthorityError, r'pre-release schema 4 \(a development build that was never '
                                                          r'released; this engine reads schema 8\)'):  # M-044: schema 8
            self.record()
        with self.assertRaisesRegex(BudgetAuthorityError, 'pre-release schema 4'):
            native_batch.cmd_admit(ns(batch='batch-auth', clip='A', kind='author', label='TEST author'))
        self.assertEqual(self.raw()['schemaVersion'], 4)          # refused, never migrated or rewritten
        self.write_raw(lambda record: record.update(status='closed', closedAtElapsed=5.0))
        batches.archive_batch(self.root, 'batch-auth', 'operator archived a pre-release batch')

    def test_another_engine_keeps_a_long_run_until_the_long_deadline(self) -> None:
        self.authorize('L')
        raw = {**self.raw(), 'schemaVersion': schema.SCHEMA_VERSION + 1}  # a future engine (M-044, W2-D9)
        for clip in raw['clips'].values():   # P0 adapt (X103): no foreign capacity policy (native_budget_batches:212)
            clip.pop('capacityClock', None)
        self.clock.advance(2500)
        self.assertFalse(batches.foreign_released(raw))          # the Shorts' 40 minutes are over; the Long's are not
        self.clock.advance(10800)
        self.assertTrue(batches.foreign_released(raw))
        shorts_only = {**raw, 'schemaVersion': 3, 'clips': {'A': raw['clips']['A']}}
        self.assertTrue(batches.foreign_released(shorts_only))   # A12's rule, read as Shorts


class ClockTests(FormatCase):
    """Each output keeps its own immutable deadline; an added Short has its own clock too (M-052, C8)."""

    def test_a_long_joins_after_minute_25_on_its_own_clock(self) -> None:
        self.clock.advance(1800)                                  # M-052: add-clip has no minute 25 either
        row = self.authorize('L')['output']
        self.assertEqual((row['authorizedElapsed'], row['preparationElapsed'], row['deadlineElapsed']),
                         (1800.0, 8705.0, 12600.0))
        record = self.record()
        self.assertEqual(formats.clip_deadlines(record, record['clips']['A'])['deliverySeconds'], 2400)
        self.assertEqual(formats.clip_deadlines(record, None)['deliverySeconds'], 12600.0)

    def test_a_short_keeps_minute_40_while_a_long_remains_active(self) -> None:
        self.director()                                          # enrolled before the Long joined
        self.authorize('L')
        api.enqueue_tasks(self.root, 'batch-auth', (task_spec('long-author', 'author', clip_id='L', parent='director',
                                                              deadline_elapsed=9000.0),))
        with self.assertRaisesRegex(registry.BudgetRefused, 'no later than the delivery deadline'):
            api.enqueue_tasks(self.root, 'batch-auth', (task_spec('short-author', 'author', parent='director',
                                                                  deadline_elapsed=3000.0),))
        self.clock.advance(2450)
        with self.assertRaisesRegex(registry.BudgetRefused, '40-minute delivery deadline has passed'):
            native_batch.cmd_admit(ns(batch='batch-auth', clip='A', kind='review', label='TEST late review'))
        native_batch.cmd_admit(ns(batch='batch-auth', clip='L', kind='review', label='TEST Long review'))
        api.enqueue_tasks(self.root, 'batch-auth', (task_spec('long-critic', 'review', clip_id='L', parent='director',
                                                              deadline_elapsed=9000.0),))

    def test_a_long_does_not_keep_short_ai_work_alive(self) -> None:
        self.director()
        self.authorize('L')
        api.enqueue_tasks(self.root, 'batch-auth', (
            task_spec('critic', 'review', clip_id='A', parent='director'),
            task_spec('long-critic', 'review', clip_id='L', parent='director', deadline_elapsed=9000.0)))
        self.running('critic')
        self.running('long-critic')
        self.clock.advance(2450)
        with mock.patch.object(launch, '_process_table', return_value=table()):
            result = api.reconcile(self.root, 'batch-auth')
        self.assertEqual(result['expiredFrozen'], ['critic'])
        tasks = self.record()['production']['tasks']
        self.assertEqual((tasks['critic']['state'], tasks['long-critic']['state']), ('cancel-requested', 'running'))
        with self.assertRaisesRegex(registry.BudgetRefused, 'Clips L are not handed off'):
            native_batch.cmd_close(ns(batch='batch-auth'))

    def test_nothing_stops_an_authorized_long_automatically(self) -> None:
        self.director()
        self.authorize('L')
        self.clock.advance(1000)
        self.authorize('M', seconds=120.0)                        # keeps the run open past L's deadline
        api.enqueue_tasks(self.root, 'batch-auth', (task_spec('long-critic', 'review', clip_id='L', parent='director',
                                                              deadline_elapsed=9000.0),))
        self.running('long-critic')
        self.clock.advance(9900)                                  # 10,900 s: past L's 10,800 s, before M's
        self.assertEqual(batch_status(self.record(), 10900.0)['clips']['L']['phase'], 'past-delivery-deadline')
        with mock.patch.object(launch, '_process_table', return_value=table()):
            self.assertEqual(api.reconcile(self.root, 'batch-auth')['expiredFrozen'], [])
        self.assertEqual(self.record()['production']['tasks']['long-critic']['state'], 'running')

    def test_closing_a_short_leaves_the_long_open(self) -> None:
        self.director()
        self.authorize('L')
        api.enqueue_tasks(self.root, 'batch-auth', (
            task_spec('short-review', 'review', clip_id='A', parent='director'),
            task_spec('long-author', 'author', clip_id='L', parent='director', deadline_elapsed=9000.0)))
        budget = self.reserve(self.project, route='draft')
        self.assertEqual(budget['allocation']['grantedSeconds'], 2280.0)   # the Short's own minute 38, not the Long's
        mp4 = test_mp4(self.work / 'attempt')             # P0 adapt: the hand-off needs a B3-verified confirmation
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-review-draft', 'output': mp4[0], 'sha256': mp4[1]})
        confirmation = handoff_confirmation(self.work / 'handoff', mp4, at=self.clock.wall)
        with b3_stand_in():
            handed = native_batch.cmd_handoff(ns(batch='batch-auth', clip='A', confirmation=confirmation))
        self.assertEqual(handed['frozenTasks'], ['short-review'])
        ready = {row['taskId']: row['refusal'] for row in api.next_ready(self.root, 'batch-auth')}
        self.assertEqual(ready, {'long-author': None})
        with self.assertRaisesRegex(registry.BudgetRefused, 'Clips B, L are not handed off'):
            native_batch.cmd_close(ns(batch='batch-auth'))
        self.clock.advance(2450)
        with self.assertRaisesRegex(registry.BudgetRefused, 'Clips L are not handed off'):
            native_batch.cmd_close(ns(batch='batch-auth'))
        self.assertEqual(self.record()['status'], 'active')

    def test_two_ten_minute_longs_do_not_fit_one_heavy_slot_beside_the_shorts(self) -> None:
        self.authorize('L')
        with self.assertRaisesRegex(registry.BudgetRefused, r'M \(long\) would finish at 10480s, after its latest '
                                                            r'9180s, behind A, B, L'):
            self.authorize('M')
        self.assertNotIn('M', self.record()['clips'])

    def test_an_authorization_is_immutable_and_an_identical_repeat_changes_nothing(self) -> None:
        first = self.authorize('L')
        again = self.authorize('L')
        self.assertEqual((again['committed'], again['replayed'], again['output']), (False, True, first['output']))
        with self.assertRaises(TaskConflict):
            self.authorize('L', seconds=900.0)
        with self.assertRaisesRegex(TaskConflict, 'different authorization'):
            self.authorize('A', 'short')
        self.write_raw(lambda record: record['clips']['L']['output'].update(deadlineElapsed=20000.0))
        with self.assertRaisesRegex(BudgetAuthorityError, 'output deadlines do not match'):
            self.record()

    def test_own_clock_shorts_join_any_active_run(self) -> None:
        """M-052 (C8, X2): a Shorts-only run takes an own-clock Short; P4's open-Long rule is for derived Shorts."""
        self.clock.advance(1800)
        row = self.authorize('N', 'short')['output']
        self.assertEqual((row['authorizedElapsed'], row['preparationElapsed'], row['deadlineElapsed']),
                         (1800.0, 3300.0, 4200.0))
        self.assertEqual(self.record()['clips']['N']['approvals'][0]['elapsed'], 1800.0)

    def test_add_clip_in_a_run_holding_a_long_passes_the_mixed_forecast(self) -> None:
        self.authorize('L')
        self.enterContext(historical_shorts())                   # P0 adapt (M-030): wall-clock Shorts

        def long_final(record: dict) -> None:
            record['clips']['L']['attempts'].append({
                'id': 'b' * 32, 'route': 'final', 'project': '/TEST/long', 'output': '/TEST/long-out', 'identity': 'c' * 64,
                'admittedElapsed': 0.0, 'outputSeconds': 600.0, 'grantedSeconds': 7805.0, 'supervisor': dict(ALIVE),
                'status': 'running', 'resultStatus': None, 'failure': None, 'completedElapsed': None, 'stages': [],
                'nested': {}, 'transientRetryOf': None})
        self.mutate('batch-auth', long_final)
        self.clock.advance(600)
        # A and B (ahead by least slack) already miss behind the Long's non-preemptible final; C would miss too, even on
        # its own clock (M-052: added at 600 s, its latest finish is 2880 s, not the batch clock's 2280 s).
        with self.assertRaisesRegex(registry.BudgetRefused, r'C \(short\) would finish at 3650s, after its latest 2880s, '
                                                            r'behind A, B\. Heavy slots: L long final owner bbbbbbbb'):  # P0 adapt: owner
            api.add_clip(self.root, 'batch-auth', 'C', api.AddedClip('fourth Short', approval('C')))
        self.assertNotIn('C', self.record()['clips'])


class IdentityTests(FormatCase):
    """Long manifests and multi-source lineage; mixed identity needs the same format."""

    def test_long_identity_uses_its_manifest_and_every_recording(self) -> None:
        project = make_long_project(self.work, 'long-v1')
        identity = registry.project_identity(project)
        plan = (project / 'LONG-PROJECT.json').read_bytes()
        self.assertEqual((identity['format'], identity['selection'], identity['projectHash']),
                         ('long', None, hashlib.sha256(plan).hexdigest()))
        self.assertEqual(identity['lineage']['sources'], sorted(source_sha(item) for item in RECORDINGS))
        request = self.work / 'long-requests/request-1/LONG-REQUEST.json'
        request.write_text(request.read_text() + ' ')
        with self.assertRaisesRegex(registry.BudgetRefused, 'Long manifest or request changed'):
            registry.project_identity(project)
        legacy = self.work / 'legacy-long'
        legacy.mkdir()
        (legacy / 'LONG-PROJECT.json').write_text(json.dumps({'schemaVersion': 1, 'canvas': {}}))
        with self.assertRaisesRegex(registry.BudgetRefused, 'without a request packet'):
            registry.project_identity(legacy)

    def test_a_long_and_its_derived_short_coexist(self) -> None:
        self.authorize('L')
        long_project = make_long_project(self.work, 'long-v1')
        self.bind('L', long_project)
        with self.assertRaisesRegex(registry.BudgetRefused, 'cuts a recording that Long L was not prepared from'):
            self.authorize('E', 'short', derived_from='L')
        self.authorize('D', 'short', derived_from='L', approval=approval('D', source_sha256=source_sha(RECORDINGS[0])))
        derived = make_project(self.work, 'derived-short', source=RECORDINGS[0], cuts=((100.0, 160.0),))
        self.bind('D', derived)
        record = self.record()
        self.assertEqual(record['clips']['D']['output']['derivedFrom'], 'L')
        self.assertEqual(len(record['clips']['L']['output']['lineage']['sources']), 3)
        whole = {'source': source_sha(RECORDINGS[0]), 'ranges': [[0.0, 600.0]]}
        self.assertTrue(same_short(whole, record['clips']['D']['projects'][0]['selection']))  # Short rule unchanged
        self.assertIsNone(output_match(record['clips']['L'], registry.project_identity(derived)))  # never the Long
        with self.assertRaisesRegex(registry.BudgetRefused, 'Output L is a long; this project is a short'):
            self.bind('L', derived)
        with self.assertRaisesRegex(registry.BudgetRefused, 'Output D is a short; this project is a long'):
            self.bind('D', long_project)
        other = make_project(self.work, 'other-source-short', source=b'another-recording', cuts=((1.0, 30.0),))
        with self.assertRaisesRegex(registry.BudgetRefused, 'derives from Long L'):
            self.bind('D', other)

    def test_multiple_source_assets_decide_which_long_a_project_is(self) -> None:
        self.authorize('L')
        self.authorize('M', seconds=120.0)                      # two 10-minute Longs do not fit one heavy slot
        self.bind('L', make_long_project(self.work, 'long-v1'))
        reprepared = make_long_project(self.work, 'long-v2', RECORDINGS + (b'long-recording-d',), request='request-2')
        with self.assertRaisesRegex(registry.BudgetRefused, 'shares Long L\'s lineage'):
            self.bind('M', reprepared)
        self.bind('L', reprepared)                               # 3 of 4 recordings: the same Long
        other = make_long_project(self.work, 'other-long', (b'other-x', b'other-y'), request='request-3', seconds=120)
        with self.assertRaisesRegex(registry.BudgetRefused, 'another request and other recordings'):
            self.bind('L', other)
        self.bind('M', other)
        one_shared = long_identity(make_long_project(self.work, 'one-shared', (RECORDINGS[0], b'other-z', b'other-w'),
                                                     request='request-4'))['lineage']
        self.assertFalse(same_long(self.record()['clips']['L']['output']['lineage'], one_shared))  # 1/5, 1/3

    def test_copied_projects_keep_their_charges(self) -> None:
        self.authorize('L')
        self.authorize('M', seconds=120.0)                      # two 10-minute Longs do not fit one heavy slot
        original = make_long_project(self.work, 'long-v1')
        self.bind('L', original)
        native_batch.cmd_admit(ns(batch='batch-auth', clip='L', kind='author', label='TEST Long author'))
        copy = self.work / 'long-copy'
        shutil.copytree(original, copy)
        with self.assertRaisesRegex(registry.BudgetRefused, 'identical content'):
            self.bind('M', copy)
        self.bind('L', copy)
        self.assertEqual((self.counters('L')['author'], self.counters('M')['author']), (1, 0))
        short_copy = self.work / 'short-copy'
        shutil.copytree(self.project, short_copy)
        with self.assertRaisesRegex(registry.BudgetRefused, 'identical content'):
            self.bind('B', short_copy)

    def test_same_format_revisions_stay_with_their_output(self) -> None:
        with self.assertRaisesRegex(registry.BudgetRefused, 're-cuts clip A'):
            self.bind('B', make_project(self.work, 'native-v2'))
        self.authorize('L')
        self.authorize('M', seconds=120.0)                      # two 10-minute Longs do not fit one heavy slot
        self.bind('L', make_long_project(self.work, 'long-v1'))
        edited = make_long_project(self.work, 'long-edit')
        plan = json.loads((edited / 'LONG-PROJECT.json').read_text())
        (edited / 'LONG-PROJECT.json').write_text(json.dumps({**plan, 'scenes': []}))
        with self.assertRaisesRegex(registry.BudgetRefused, 'shares Long L\'s lineage'):
            self.bind('M', edited)
        self.bind('L', edited)
        self.assertEqual([row['selection'] for row in self.record()['clips']['L']['projects']], [None, None])

    def test_a_long_binds_its_scaffold_and_never_a_longer_cut_than_authorized(self) -> None:
        self.authorize('L')                                       # authorized for 600 s
        scaffold = make_long_project(self.work, 'scaffold')
        plan = json.loads((scaffold / 'LONG-PROJECT.json').read_text())
        del plan['canvas']                                        # prepare-longform writes no canvas yet
        (scaffold / 'LONG-PROJECT.json').write_text(json.dumps(plan))
        self.bind('L', scaffold)
        with self.assertRaisesRegex(registry.BudgetRefused, 'authorized for 600 s and this project runs 900.0 s'):
            self.bind('L', make_long_project(self.work, 'longer-cut', seconds=900))
        self.bind('L', make_long_project(self.work, 'shorter-cut', seconds=580))

    def test_the_output_reader_names_batch_clip_and_format_without_short_approvals(self) -> None:
        self.authorize('L')
        project = make_long_project(self.work, 'long-v1')
        self.bind('L', project)
        long = api.output_for_project(self.root, project)
        self.assertEqual((long['batchId'], long['clipId'], long['format'], long['clock'], long['deadlineElapsed']),
                         ('batch-auth', 'L', 'long', 'own', 10800.0))
        self.assertEqual((long['preparationElapsed'], len(long['lineage']['sources'])), (6905.0, 3))
        self.assertIsNone(api.approval_for_project(self.root, project)['current'])
        short = api.output_for_project(self.root, self.project)
        self.assertEqual((short['clipId'], short['format'], short['clock'], short['deadlineElapsed']),
                         ('A', 'short', 'batch', 2400))
        self.assertIsNone(api.output_for_project(self.root, make_project(self.work, 'unbound', source=b'x')))

    def test_a_long_project_does_not_launch_through_the_short_path(self) -> None:
        self.authorize('L')
        project = make_long_project(self.work, 'long-v1')
        self.bind('L', project)
        self.assertEqual(registry.project_output_seconds(project), 600.0)
        with self.assertRaisesRegex(registry.BudgetRefused, 'Long public entry'):
            binding.reserve_launch(project, self.work / 'long-out', 'final', {})


class MixedForecastTests(unittest.TestCase):
    """Mixed admission and Long launch decisions over in-memory records (the supervisor identity is stubbed)."""

    def setUp(self) -> None:
        patches = [mock.patch.object(launch, 'own_identity', return_value=dict(ALIVE)),
                   mock.patch.object(launch, '_process_table', return_value={4242: (1, 4242, ALIVE['started'])}),
                   mock.patch.object(forecast, 'heavy_lane_capacity', return_value=3)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def record(self, slots: int = 1, seconds: float = 600.0) -> dict:
        """Shorts A (60 s) and B (40 s) on the batch clock and Long L authorized at 0."""
        with fake_clock(FakeClock()):
            record = new_batch_record(BatchSpec('batch-mix', ('A', 'B'), (), slots,
                                                approvals={clip: approval(clip) for clip in ('A', 'B')}), start_anchor())
        authorize_output(record, long_request('L', seconds), 0.0)
        return record

    def launch(self, record: dict, request: tuple, elapsed: float) -> object:
        clip, route, seconds, windows = (*request, None)[:4]
        return launch.admit_launch(record, launch.LaunchRequest(clip, route, f'id-{clip}-{route}', ('/TEST/p', '/TEST/o'),
                                                                seconds, windows), elapsed)

    def finished(self, record: dict, clip: str, route: str, at: float, windows: float | None = None) -> None:
        decision = self.launch(record, (clip, route, record['clips'][clip]['output']['outputSeconds'], windows), at)
        self.assertTrue(decision.allowed, decision.reason)
        launch.record_outcome(record, {'clipId': clip, 'attemptId': decision.detail['attempt']['id']},
                              {'status': 'ok', 'successStatuses': ('ok',), 'stages': [{'phase': 'TEST'}]}, at + 1)

    def expire_shorts(self, record: dict) -> None:
        for clip in ('A', 'B'):
            record['clips'][clip]['state'] = 'handed-off'

    def test_short_admission_is_refused_by_name_when_a_running_long_makes_it_miss(self) -> None:
        self.enterContext(historical_shorts())                   # P0 adapt (M-030): wall-clock Shorts
        record = self.record()
        self.expire_shorts(record)
        self.finished(record, 'L', 'preview', 100.0)
        final = self.launch(record, ('L', 'final', 600.0), 3000.0)  # non-preemptible until about 5275 s
        self.assertTrue(final.allowed, final.reason)
        with self.assertRaisesRegex(TaskRefused, r'N \(short\) would finish at 5600s, after its latest 5380s.*'
                                                 r'Heavy slots: L long final owner'):  # P0 adapt: owner
            authorize_output(record, short_request('N'), 3100.0)
        self.assertNotIn('N', record['clips'])
        record['poolSlots'] = 3                                 # a free slot: the same Short fits its 40 minutes
        self.assertFalse(authorize_output(record, short_request('N'), 3100.0)['replayed'])

    def test_a_long_waits_behind_urgent_shorts_for_a_bounded_time(self) -> None:
        self.enterContext(historical_shorts())                   # P0 adapt (M-030): wall-clock Shorts
        record = self.record()
        waiting = self.launch(record, ('L', 'preview', 600.0), 600.0)
        self.assertFalse(waiting.allowed)
        self.assertRegex(waiting.reason, r'Long L preview waits.*A \(short\) would finish at 3665s, after its latest '
                                         r'2280s.*B \(short\)')
        self.assertTrue(mixed_status(record, 600.0)['outputs']['L']['fits'])  # waiting has not cost it its deadline
        self.assertFalse(self.launch(record, ('L', 'preview', 600.0), 1650.0).allowed)
        # The bound: A's latest safe start, 2280 - 625 (its draft) = 1655 s, never past the Shorts' 2400 s deadline.
        # A Short that has not launched by then misses whatever the Long does, so it no longer holds the Long back.
        admitted = self.launch(record, ('L', 'preview', 600.0), 1656.0)
        self.assertTrue(admitted.allowed, admitted.reason)
        attempt = admitted.detail['attempt']
        self.assertEqual(attempt['admittedElapsed'] + attempt['grantedSeconds'], 6905.0)  # L's own grant end less its final

    def test_packet_windows_let_a_long_preview_launch_beside_the_shorts(self) -> None:
        record = self.record()
        request = launch.LaunchRequest('L', 'preview', 'id-L-preview', ('/TEST/p', '/TEST/o'), 600.0, 12.0)
        decision = launch.admit_launch(record, request, 600.0)   # 308.5 s of preview, then A and B still fit
        self.assertTrue(decision.allowed, decision.reason)
        # The attempt row keeps no window seconds, so the running preview is held to the bound (a stated limit).
        self.assertEqual(mixed_status(record, 600.0)['previewBasis'], {'L': 'whole-program bound (no preview packet yet)'})

    def test_a_long_final_is_admitted_by_its_forecast_never_by_the_preparation_deadline_alone(self) -> None:
        record = self.record()
        self.expire_shorts(record)
        self.finished(record, 'L', 'preview', 100.0)
        on_time = self.launch(record, ('L', 'final', 600.0), 6905.0)          # the latest final start: ends at 9180
        attempt = on_time.detail['attempt']
        self.assertEqual(attempt['admittedElapsed'] + attempt['grantedSeconds'], 9180.0)  # grant end D_g
        record = self.record()
        self.expire_shorts(record)
        self.finished(record, 'L', 'preview', 100.0)
        status = batch_status(record, 6906.0)['clips']['L']
        self.assertTrue(status['slaMiss'])
        self.assertRegex(status['actions'][0], '^SLA MISS: no final of this Long can still end')
        self.assertRegex(self.launch(record, ('L', 'final', 600.0), 6906.0).reason,
                         'Forecast misses the handoff deadline.*A Long has no draft route: report the SLA risk now')
        self.assertTrue(self.launch(record, ('L', 'final', 580.0), 6906.0).allowed)  # a shorter actual cut still fits

    def test_status_names_the_long_deadlines_while_they_can_be_corrected(self) -> None:
        record = self.record()
        self.expire_shorts(record)
        early = batch_status(record, 600.0)['clips']['L']['actions']
        self.assertEqual(early, ['long-final-deadline: the preview must launch by minute 74 (whole-program bound (no '
                                 'preview packet yet); with no windows at all, minute 111) and the final by minute 115 '
                                 'of its clock; after that no MP4 can reach its hand-off by minute 180'])
        self.assertFalse(batch_status(record, 600.0)['clips']['L']['slaMiss'])
        late = batch_status(record, 4500.0)['clips']['L']
        self.assertRegex(late['actions'][0], '^long-final-at-risk: a whole-program-bound preview no longer fits')
        self.assertFalse(late['slaMiss'])
        self.finished(record, 'L', 'preview', 4500.0, windows=12.0)             # the packet's 3 x 120 frames
        self.assertRegex(batch_status(record, 4600.0)['clips']['L']['actions'][0],
                         '^long-final-at-risk: launch the final by minute 115 of its clock')

    def test_a_long_launches_as_soon_as_the_shorts_are_delivered(self) -> None:
        record = self.record()
        for clip in ('A', 'B'):
            record['clips'][clip]['deliveries'].append({'kind': 'draft', 'output': '/TEST/x.mp4', 'sha256': 'a' * 64,
                                                        'attemptId': 'd' * 32, 'elapsed': 1400.0})
        self.assertTrue(self.launch(record, ('L', 'preview', 600.0), 1400.0).allowed)

    def test_a_new_short_cannot_starve_a_long_with_less_slack(self) -> None:
        self.enterContext(historical_shorts())                   # P0 adapt (M-030): wall-clock Shorts
        record = self.record(seconds=900.0)
        self.expire_shorts(record)
        self.finished(record, 'L', 'preview', 100.0)
        with self.assertRaisesRegex(TaskRefused, r'N \(short\) would finish at 8688s, after its latest 7280s, '
                                                 r'behind L'):
            authorize_output(record, short_request('N'), 5000.0)
        self.assertTrue(mixed_status(record, 5000.0)['outputs']['L']['fits'])

    def test_a_new_long_is_refused_by_name_when_it_cannot_fit(self) -> None:
        record = self.record(seconds=900.0)
        self.expire_shorts(record)
        self.finished(record, 'L', 'preview', 50.0)
        self.assertTrue(self.launch(record, ('L', 'final', 900.0), 100.0).allowed)
        with self.assertRaisesRegex(TaskRefused, r'M \(long\) would finish at 10435s, after its latest 9080s.*'
                                                 r'L long final owner'):  # P0 adapt: owner (mixed_forecast.py:206)
            authorize_output(record, long_request('M', 900.0), 200.0)

    def test_long_launches_use_long_routes_limits_and_deadlines(self) -> None:
        record = self.record()
        self.assertRegex(self.launch(record, ('L', 'draft', 600.0), 100.0).reason, 'A Long export has no draft route')
        short = self.launch(record, ('A', 'final', 60.0), 100.0)
        self.assertEqual(short.detail['attempt']['admittedElapsed'] + short.detail['attempt']['grantedSeconds'], 2280.0)
        self.expire_shorts(record)
        late = self.launch(record, ('L', 'preview', 600.0), 6905.0)             # preview + its final end past 9180
        self.assertRegex(late.reason, 'Forecast misses the handoff deadline.*A Long has no draft route')
        self.assertEqual(formats.clip_limits(record, record['clips']['L'])['exportAttempt'], 2)

    def test_capacity_is_read_per_format_at_each_outputs_own_duration(self) -> None:
        asked = []

        def capacity(seconds: float | None = None, fmt: str = 'short') -> int:
            asked.append((seconds, fmt))
            return 3 if fmt == 'short' else 1                     # a Short profile only: no Long profile
        record = self.record(slots=3)
        with mock.patch.object(forecast, 'heavy_lane_capacity', side_effect=capacity):
            self.assertEqual(forecast.slot_count(record), 1)      # the Long's own profile allows one slot
            self.assertIn((600.0, 'long'), asked)
            self.assertFalse(any(fmt == 'short' for _, fmt in asked))  # Shorts of unknown duration are excluded
            self.expire_shorts(record)
            del record['clips']['L']
            self.assertEqual(forecast.slot_count(record, 60.0), 3)  # a Shorts-only run keeps its Short profile

    def test_the_report_names_each_format_and_the_mixed_forecast(self) -> None:
        record = self.record()
        status = batch_status(record, 600.0)
        long, short = status['clips']['L'], status['clips']['A']
        self.assertEqual((long['format'], long['clock'], long['deadlineElapsed'], long['demand']['finalSeconds']),
                         ('long', 'own', 10800.0, 2275.0))
        self.assertEqual(long['demand']['previewBasis'], 'whole-program bound (no preview packet yet)')
        self.assertEqual((short['format'], short['clock'], short['deadlineElapsed']), ('short', 'batch', 2400))
        self.assertEqual(set(status['mixed']['outputs']), {'A', 'B', 'L'})
        self.assertEqual(status['deliveryRemainingSeconds'], 10200.0)   # the run lives until its latest output
        self.assertEqual((batch_status(record, 1800.0)['phase'], batch_status(record, 1800.0)['clips']['A']['phase']),
                         ('preparation', 'export-and-handoff'))


if __name__ == '__main__':
    unittest.main()
