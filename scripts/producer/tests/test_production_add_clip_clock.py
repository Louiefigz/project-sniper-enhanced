"""M-052 (P1 Step B9, C8; C-2, X2, X121, X144): an added Short gets its own clock; one same-job function.

A Short added with ``add-clip`` is authorized as its own output: its 40 counted minutes start when it is added,
the forecast admits it by name at any minute, and the same job (the same folded title, source, transcript, word
ranges and texts, whatever its derived seconds, or one in another clip's recorded lineage) is refused by name.
Overlapping source seconds alone never refuse; the check is recorded on the adding event, shown in status and
recorded as one ``coordinator-note`` decision (the recorded-check details: ``test_production_duplication_check``).

Authority tests use real private files and kernel locks under a temporary root (``RegistryCase``); every
approval, handle and recording is a TEST fixture.
"""
from __future__ import annotations

import json
import unittest
from dataclasses import replace
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _budget_fixture import CHANGE_REASON, DIRECTOR, FINGERPRINT, approval, host_turn, source_sha, table, task_spec
from test_native_budget_registry import RegistryCase, ns
import native_batch
from studio import native_budget_forecast as forecast
from studio import native_budget_launch as launch
from studio import native_budget_registry as registry
from studio.native_budget_policy import admit_new_clip
from studio.native_budget_report import batch_status
from studio.production import api
from studio.production.approvals import ADDED_REASON, ApprovalChange
from studio.production.claims import ClaimRef, Enrollment
from studio.production.outputs import OutputAuthorization
from studio.production.tasks import TaskConflict

SAME_JOB = ('Clip {0} already carries this approved script: a retry, re-add or rename of the same job never gets a new '
            'clock; ')


def script(first: int, last: int, *more: tuple[int, int]) -> dict:
    """Approval fields for inclusive TEST word ranges (word i spans source second i to i + 0.9)."""
    rows = ((first, last), *more)
    return {'word_ranges': rows, 'word_texts': tuple(f'w{index}' for a, b in rows for index in range(a, b + 1)),
            'ranges': tuple((float(a), b + 1.0) for a, b in rows)}


def row(clip: str, overlap: float, script_is: str, title_is: str) -> dict:
    """One expected duplication-check row (X121)."""
    return {'clip': clip, 'overlapSeconds': overlap,
            'identity': {'script': script_is, 'title': title_is, 'lineage': False}}


class AddClipCase(RegistryCase):
    """A running Shorts-only batch (A and B declared with approvals at start) and one heavy slot."""

    def setUp(self) -> None:
        """One heavy slot, as the format tests declare it (no host pool record is read)."""
        super().setUp()
        patch = mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1)
        patch.start()
        self.addCleanup(patch.stop)

    def add(self, clip: str, value: object) -> dict:
        """``add-clip`` of ``clip`` with the approval ``value``, through the locked API."""
        return api.add_clip(self.root, 'batch-auth', clip, api.AddedClip(f'TEST operator added {clip}', value))

    def trail(self, event: str) -> list[dict]:
        """Every trail line of one event kind, in order."""
        lines = (self.root / 'batches/batch-auth/events.jsonl').read_text().splitlines()
        return [item for item in map(json.loads, filter(None, lines)) if item.get('event') == event]

    def running(self, task_id: str) -> None:
        """Claim and attach a TEST host turn for ``task_id``."""
        claimed = api.claim_task(self.root, 'batch-auth', task_id, host_turn(task_id))
        ref = ClaimRef(task_id, claimed['epoch'], claimed['token'])
        api.attach_task(self.root, 'batch-auth', ref, host_turn(task_id))


class OwnClockTests(AddClipCase):
    """C8: the added Short's counted time starts at its own authorization, at any minute."""

    def test_added_short_has_its_own_forty_minutes(self) -> None:
        """Added at 1200 s: its own minute 40 is 3600 s, and status counts its time from 1200 s."""
        self.clock.advance(1200)
        added = self.add('C', approval('C'))
        output = added['output']
        self.assertEqual((output['format'], output['authorizedElapsed'], output['preparationElapsed'],
                          output['deadlineElapsed']), ('short', 1200.0, 2700.0, 3600.0))
        self.assertEqual((added['approval']['elapsed'], added['approval']['reason']), (1200.0, ADDED_REASON))
        self.assertEqual(self.trail('clip-added')[-1]['authorizedElapsed'], 1200.0)
        self.clock.advance(60)
        status = native_batch.cmd_status(ns(batch='batch-auth'))['clips']
        self.assertEqual((status['C']['clock'], status['C']['totalElapsedSeconds'],
                          status['C']['countedProductionSeconds']), ('own', 60.0, 60.0))
        self.assertEqual((status['A']['deadlineElapsed'], status['C']['deadlineElapsed']), (2400, 3600.0))

    def test_status_full_wall_budget_counts_from_the_added_shorts_own_clock(self) -> None:
        """X144 minor 4: at 2500 s (past the batch's minute 40), C added at 1200 s still has 1100 s to deliver."""
        self.clock.advance(1200)
        self.add('C', approval('C'))
        self.clock.advance(1300)
        budget = native_batch.cmd_status(ns(batch='batch-auth', full=True))['clips']['C']['production']['wallBudget']
        self.assertEqual((budget['preparationRemainingSeconds'], budget['launchCutoffRemainingSeconds'],
                          budget['deliveryRemainingSeconds']), (200.0, 980.0, 1100.0))

    def test_add_after_minute_25_is_admitted_by_name(self) -> None:
        """No batch-wall minute 25: an add at 1600 s is admitted; a Short that cannot fit is refused by name."""
        self.clock.advance(1600)
        self.assertTrue(admit_new_clip(self.record(), 'C', 1600.0).allowed)       # no batch-wall minute 25
        self.assertEqual(self.add('C', approval('C'))['output']['deadlineElapsed'], 4000.0)
        too_long = approval('D', title='TEST 300-second Short', **script(1000, 1299))   # its own draft misses
        with self.assertRaisesRegex(registry.BudgetRefused, r'Output D cannot be admitted: the forecast misses\. D '):
            self.add('D', too_long)
        self.assertNotIn('D', self.record()['clips'])

    def test_expired_short_is_frozen_while_a_later_short_keeps_the_run_open(self) -> None:
        """In a Shorts-only run an expired Short's live work stops while a later added Short keeps the run open."""
        api.enroll_director(self.root, 'batch-auth', Enrollment('director', DIRECTOR, 'v1', FINGERPRINT))
        self.clock.advance(1200)
        self.add('C', approval('C'))                                        # a Shorts-only run: C's minute 40 is 3600
        api.enqueue_tasks(self.root, 'batch-auth', (
            task_spec('critic-a', 'review', clip_id='A', parent='director'),
            task_spec('critic-c', 'review', clip_id='C', parent='director', deadline_elapsed=3500.0)))
        self.running('critic-a')
        self.running('critic-c')
        self.clock.advance(1250)                                            # 2450: A's own deadline passed, C's not
        with mock.patch.object(launch, '_process_table', return_value=table()):
            self.assertEqual(api.reconcile(self.root, 'batch-auth')['expiredFrozen'], ['critic-a'])
        tasks = self.record()['production']['tasks']
        self.assertEqual((tasks['critic-a']['state'], tasks['critic-c']['state']), ('cancel-requested', 'running'))
        with self.assertRaisesRegex(registry.BudgetRefused, 'Clips C are not handed off'):
            native_batch.cmd_close(ns(batch='batch-auth'))


class SameJobTests(AddClipCase):
    """C-2: only an effective duplicate (the same job identity, or one in a clip's lineage) is refused."""

    def test_same_identity_readd_refused(self) -> None:
        """Another clip's exact title and script under a new id is refused by name (add-clip and authorize-output)."""
        whole = SAME_JOB.format('A') + 'change it with change-approval --clip A$'
        with self.assertRaisesRegex(registry.BudgetRefused, whole):
            self.add('X', approval('A'))                                    # A's exact title and script, a new id
        self.add('C', approval('C'))
        with self.assertRaisesRegex(registry.BudgetRefused, SAME_JOB.format('C')):
            self.add('Y', approval('C'))
        with self.assertRaisesRegex(registry.BudgetRefused, SAME_JOB.format('C')):   # the one function guards both
            api.authorize_output(self.root, 'batch-auth', OutputAuthorization(
                'Z', 'short', 'TEST own-clock Short', 'TEST operator', approval=approval('C')))
        self.assertEqual((sorted(self.record()['clips']), len(self.trail('clip-added'))), (['A', 'B', 'C'], 1))

    def test_same_words_and_title_with_other_seconds_is_the_same_job(self) -> None:
        """X144 MAJOR-1: A's title and words with every cut nudged 0.05 s into the word gaps are still A's job."""
        nudged = approval('A', ranges=((9.95, 39.95), (49.95, 79.95)))
        with self.assertRaisesRegex(registry.BudgetRefused, SAME_JOB.format('A')):
            self.add('X', nudged)
        self.assertNotIn('X', self.record()['clips'])

    def test_a_whitespace_or_nfc_only_retitle_is_the_same_job(self) -> None:
        """X144 O-7: titles compare after NFC, trimming and collapsing whitespace; a real new title is distinct."""
        self.add('C', approval('C', title='TEST caf\u00e9 C'))
        for title in ('  TEST   caf\u00e9 C ', 'TEST cafe\u0301 C'):
            with self.subTest(title=title), self.assertRaisesRegex(registry.BudgetRefused, SAME_JOB.format('C')):
                self.add('D', approval('C', title=title))
        self.assertEqual(self.add('D', approval('C', title='TEST caf\u00e9 D'))['committed'], True)

    def test_a_lineage_three_renames_back_is_the_same_job(self) -> None:
        """Every earlier approval of C (four rows, the bound) stays C's job; each re-add is refused naming C."""
        titles = ('TEST title C', 'TEST rename 1', 'TEST rename 2', 'TEST rename 3')
        self.add('C', approval('C'))
        for title in titles[1:]:
            api.record_script_change(self.root, 'batch-auth', 'C', ApprovalChange(approval('C', title=title),
                                                                                  CHANGE_REASON))
        for title in titles:
            with self.subTest(title=title), self.assertRaisesRegex(registry.BudgetRefused, SAME_JOB.format('C')):
                self.add('D', approval('C', title=title))

    def test_a_derived_short_gets_the_same_job_guard(self) -> None:
        """E-LS-5: a Short derived from a Long of this run is refused as another clip's job like any Short."""
        api.authorize_output(self.root, 'batch-auth', OutputAuthorization('L', 'long', 'TEST Long', 'TEST operator',
                                                                          output_seconds=600.0))
        self.mutate('batch-auth', lambda record: record['clips']['L']['output'].update(
            lineage={'request': 'a' * 64, 'sources': [source_sha()]}))       # the Long's bound recording is A's
        with self.assertRaisesRegex(registry.BudgetRefused, SAME_JOB.format('A')):
            api.authorize_output(self.root, 'batch-auth', OutputAuthorization(
                'X', 'short', 'TEST derived Short', 'TEST operator', approval=approval('A'), derived_from='L'))
        self.assertNotIn('X', self.record()['clips'])

    def test_change_approval_rename_keeps_lineage_and_clock(self) -> None:
        """A rename goes through change-approval: the clock stays; the old and new identities both stay that job."""
        self.clock.advance(300)
        output = self.add('C', approval('C'))['output']
        self.clock.advance(100)
        renamed = api.record_script_change(self.root, 'batch-auth', 'C',
                                           ApprovalChange(approval('C', title='TEST renamed C'), CHANGE_REASON))
        self.assertEqual(renamed['changed'], ['title'])
        self.assertEqual(self.record()['clips']['C']['output'], output)    # the rename keeps the clock
        for candidate in (approval('C'), approval('C', title='TEST renamed C')):   # its lineage, then its current
            with self.subTest(title=candidate.title), self.assertRaisesRegex(registry.BudgetRefused,
                                                                             SAME_JOB.format('C')):
                self.add('D', candidate)
        self.assertNotIn('D', self.record()['clips'])

    def test_distinct_overlapping_clip_admitted_with_recorded_duplication_check(self) -> None:
        """Overlap alone never refuses: the check is on the event, in status and in one coordinator-note decision."""
        trim = approval('T', title='TEST trim of A', **script(12, 39, (50, 79)))   # 58 of A's 60 seconds
        added = self.add('T', trim)
        expected = [row('A', 58.0, 'different', 'different')]
        event = self.trail('clip-added')[-1]
        self.assertEqual((added['duplicationCheck'], event['duplicationCheck']), (expected, expected))
        decisions = self.trail('coordination-decision')
        self.assertEqual((added['decisions'], added['pendingDecisions']), (decisions, []))
        self.assertEqual({key: decisions[0][key] for key in ('decisionId', 'outputId', 'kind', 'author', 'refs')},
                         {'decisionId': 'duplication-check.' + event['approval'][:32], 'outputId': 'T',
                          'kind': 'coordinator-note', 'refs': [],
                          'author': {'role': 'operator', 'taskId': None, 'epoch': None, 'handle': None,
                                     'recordedBy': 'TEST coordinator'}})
        status = native_batch.cmd_status(ns(batch='batch-auth'))['clips']
        self.assertEqual((status['T']['duplicationCheck'], 'duplicationCheck' in status['A']), (expected, False))
        self.assertEqual(self.trail('coordination-decision'), decisions)   # status writes no second line
        waited = batch_status(self.record(), 0.0)['clips']        # what wait and close show: no trail, no key
        self.assertEqual(['duplicationCheck' in waited[clip] for clip in ('A', 'T')], [False, False])

    def test_same_script_new_title_via_add_clip_is_a_distinct_job_with_recorded_duplication_check(self) -> None:
        """The title is part of the identity: the same script under a new title is a distinct job on its own clock."""
        self.add('C', approval('C'))
        self.clock.advance(200)
        added = self.add('D', approval('D'))                                # C's script under its own title
        self.assertEqual((added['output']['authorizedElapsed'], added['duplicationCheck']),
                         (200.0, [row('C', 30.0, 'same', 'different')]))
        authorized = api.authorize_output(self.root, 'batch-auth', OutputAuthorization(
            'E', 'short', 'TEST own-clock Short', 'TEST operator', approval=approval('E')))
        expected = [row('C', 30.0, 'same', 'different'), row('D', 30.0, 'same', 'different')]
        self.assertEqual((authorized['duplicationCheck'], self.trail('output-authorized')[-1]['duplicationCheck']),
                         (expected, expected))
        self.assertEqual(native_batch.cmd_status(ns(batch='batch-auth'))['clips']['E']['duplicationCheck'], expected)
        lines = self.trail('coordination-decision')
        self.assertEqual([(item['outputId'], item['author']['recordedBy']) for item in lines],
                         [('D', 'TEST coordinator'), ('E', 'TEST operator')])   # the output row's recorder


class ReplayTests(AddClipCase):
    """E-REPLAY-1 and a same-id conflict; a new script; the added approval reads back."""

    def test_identical_retry_is_a_replay(self) -> None:
        """E-REPLAY-1: an identical retry after a lost acknowledgement commits and records nothing."""
        first = self.add('D', approval('D', title='TEST trim of A', **script(12, 39, (50, 79))))
        files = [self.root / 'batches/batch-auth' / name for name in ('authority.json', 'events.jsonl')]
        before = [path.read_bytes() for path in files]
        self.clock.advance(5)                                               # a lost acknowledgement, then a retry
        again = self.add('D', approval('D', title='TEST trim of A', **script(12, 39, (50, 79))))
        self.assertEqual((again['committed'], again['replayed'], again['output'], again['approval']),
                         (False, True, first['output'], first['approval']))
        self.assertEqual((again['duplicationCheck'], again['decisions'], again['pendingDecisions']),
                         (first['duplicationCheck'], [], []))
        self.assertEqual([path.read_bytes() for path in files], before)    # nothing committed, nothing recorded

    def test_same_id_other_approval_conflicts(self) -> None:
        """The same clip id with another approval, or a declared clip re-added, is a conflict."""
        self.add('C', approval('C'))
        with self.assertRaisesRegex(TaskConflict, 'Output C already exists with a different authorization'):
            self.add('C', approval('C', title='TEST another title'))
        with self.assertRaisesRegex(TaskConflict, 'Output A already exists with a different authorization'):
            self.add('A', approval('Q'))                                    # a declared clip is never re-added

    def test_a_new_script_is_admitted(self) -> None:
        """A script no clip overlaps is admitted with a null check and no decision."""
        added = self.add('C', approval('C'))
        self.assertEqual((added['committed'], added['duplicationCheck'], added['decisions']), (True, None, []))
        self.assertEqual((self.trail('clip-added')[-1]['duplicationCheck'], self.trail('coordination-decision')),
                         (None, []))

    def test_added_short_approval_reads_back(self) -> None:
        """The chained reader reads the added clip's approval back through its clip-added event."""
        added = self.add('C', replace(approval('C'), recorded_by='TEST operator'))
        read = api.read_approval(self.root, 'batch-auth', 'C')
        self.assertEqual((read['current'], read['history']), (added['approval'], [added['approval']]))
        self.assertEqual(self.record()['clips']['C']['output']['recordedBy'], 'TEST operator')


if __name__ == '__main__':
    unittest.main()
