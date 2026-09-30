"""M-042's counted section reservations over the real chunk fixture (X125 N2, X168): what a row reserves.

A started row whose early review can still run reserves one slot; a row that can never progress reserves
nothing (X168 P2-M1): an early review frozen or cancelled before it ran, an author frozen before it ran, an
author asked to stop or revoked. Only a current row's own early review may use a reserved slot (P2-m1); a
row whose author has not started adds two slots once, not per row (P2-n2); a clip's family plan that cannot
be read or verified refuses a run-scoped AI claim by name (P2-n3). The fixture is ``ChunkFixture`` (a private
batch, TEST host handles, one free slot after setUp); claims run on its in-memory record, and no test starts
a child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from _production_chunk_fixture import ChunkFixture
from studio.production import section_chunk_liveness as liveness
from studio.production.claims import claim
from studio.production.tasks import TaskRefused, active_ai

NOT_READY = 'only a ready task can be claimed'


class ReservationCase(unittest.TestCase):
    """The liveness tests' scenario: the chunk reviewer ready again, every other fixture task as registered."""

    def setUp(self) -> None:
        """The chunk reviewer reset to ready with its charge undone; the last row's author and early review."""
        self.fixture = ChunkFixture(self)
        self.host = self.fixture.host
        self.record = self.host.budget.record()
        self.tasks = self.record['production']['tasks']
        self.task = self.tasks[self.fixture.ref.task_id]
        self.task.update(state='ready', claim=None, handle=None, charged=False, epochs=0)
        self.record['production']['ai']['charged'] -= 1
        self.record['clips']['A']['counters']['review'] -= 1
        self.last = self.host.context['assignments'][-1]
        self.author = self.tasks[self.last['authorTaskId']]
        self.early = next(task for task in self.tasks.values()
                          if task.get('sectionBinding', {}).get('role') == 'early-review'
                          and task['sectionBinding']['authorTaskId'] == self.author['id'])

    def free(self, count: int) -> None:
        """Pin the ceiling so exactly ``count`` slots are free."""
        self.record['production']['ai']['slots'] = active_ai(self.record) + count

    def rewind(self, task: dict, state: str = 'ready') -> dict:
        """A task that has not run: ``ready`` (dormant), or ``cancelled`` (frozen before it ran), holding nothing."""
        task.update(state=state, claim=None, handle=None, receipts=[], unresolved=False, endConfirmed=False,
                    terminalElapsed=self.host.budget.elapsed if state == 'cancelled' else None,
                    reason='TEST frozen before it ran' if state == 'cancelled' else None)
        return task

    def claimed(self, task: dict) -> str:
        """``claimed``, or the refusal text; the in-memory record is the fixture's."""
        try:
            claim(self.record, task['id'], self.host.handle('director'), self.host.budget.elapsed)
        except TaskRefused as refusal:
            return str(refusal)
        return 'claimed'

    def rows(self, *extra: dict) -> object:
        """Patch the rows a claim competes with to the fixture's current rows (plus ``extra``), read without a
        chunk request, as other Long work reads its clip's family plan."""
        rows = [(row, None) for row in (*self.host.context['assignments'], *extra)]
        return patch.object(liveness, '_current_rows', return_value=rows)


class DeadRowTests(ReservationCase):
    """X168 P2-M1: a row that can never progress reserves nothing, so the last slot stays claimable."""

    def test_an_early_review_frozen_before_it_ran_reserves_nothing(self) -> None:
        """The author completed; its early review was cancelled before it ran and is never claimable again."""
        self.rewind(self.early, 'cancelled')
        self.free(1)
        self.assertIn(NOT_READY, self.claimed(self.early))
        self.assertEqual(self.claimed(self.task), 'claimed')

    def test_an_author_frozen_before_it_ran_is_not_a_section_to_author(self) -> None:
        """The row's author and early review were cancelled before they ran: the row is not dormant (no +2)."""
        self.rewind(self.author, 'cancelled')
        self.rewind(self.early, 'cancelled')
        self.free(1)
        self.assertIn(NOT_READY, self.claimed(self.author))
        self.assertEqual(self.claimed(self.task), 'claimed')

    def test_an_author_asked_to_stop_or_revoked_reserves_nothing(self) -> None:
        """A live author asked to stop can only end cancelled, and a revoked one superseded: neither result is a
        completed one its early review could bind to, so the row reserves nothing while the author still runs."""
        self.rewind(self.early)
        self.author.update(state='running', handle=self.host.handle('TEST-live-author'), receipts=[],
                           terminalElapsed=None, unresolved=False, endConfirmed=False)
        self.free(1)
        with self.assertRaisesRegex(TaskRefused, r'\(1 free, 1 reserved'):
            claim(self.record, self.task['id'], self.host.handle('director'), self.host.budget.elapsed)
        for change in ({'state': 'cancel-requested', 'cancelRequested': True}, {'revoked': True}):
            with self.subTest(**change):
                self.author.update({'state': 'running', 'cancelRequested': False, 'revoked': False, **change})
                self.assertIsNone(liveness.reviewer_liveness_refusal(self.record, self.task))
        self.assertEqual(self.claimed(self.task), 'claimed')


class ExemptionAndDormancyTests(ReservationCase):
    """P2-m1: only a current row's own early review may use its reservation; P2-n2: +2 once for dormant rows."""

    def test_a_stale_generation_early_review_is_not_exempt(self) -> None:
        """With the one free slot reserved for a running author's early review, that review is admitted; an early
        review of an author outside the current rows (an older generation) waits by name."""
        self.rewind(self.early)
        self.author.update(state='running', handle=self.host.handle('TEST-live-author'), receipts=[],
                           terminalElapsed=None, unresolved=False, endConfirmed=False)
        stale = copy.deepcopy(self.early)
        stale.update(id='TEST-stale-early')
        stale['sectionBinding'].update(authorTaskId='TEST-older-author', generation=self.last['generation'] + 1)
        self.tasks[stale['id']] = stale
        self.free(1)
        with self.rows():
            self.assertIsNone(liveness.reviewer_liveness_refusal(self.record, self.early))
            refusal = liveness.reviewer_liveness_refusal(self.record, stale)
        self.assertRegex(refusal, r'^AI task TEST-stale-early must leave an AI slot .*\(1 free, 1 reserved')

    def test_dormant_rows_add_two_slots_once(self) -> None:
        """Two rows whose authors have not started: other work needs three free slots, not five (+2 once)."""
        self.rewind(self.author)
        self.rewind(self.early)
        second = {**copy.deepcopy(self.author), 'id': 'TEST-second-author'}
        self.tasks[second['id']] = second
        row = {**self.last, 'sectionId': 'TEST-mid', 'authorTaskId': second['id']}
        with self.rows(row):
            self.free(2)
            self.assertRegex(liveness.reviewer_liveness_refusal(self.record, self.task),
                             r'\(2 free, 0 reserved .* 2 section\(s\) not yet authored')
            self.free(3)
            self.assertIsNone(liveness.reviewer_liveness_refusal(self.record, self.task))


class FamilyPlanPinTests(ReservationCase):
    """P2-n3: every Long or run-scoped AI claim reads the clip's family plan; a bad pin refuses by name."""

    def test_a_run_scoped_claim_is_refused_by_name_for_a_missing_or_tampered_plan(self) -> None:
        """With a valid family pin a run-scoped AI claim is admitted; a missing plan file and changed plan bytes
        each refuse it by name (fail closed), and nothing is committed to the in-memory record."""
        work = copy.deepcopy(self.task)
        work.pop('sectionBinding')
        work.update(id='TEST-run-scoped', clipId=None)
        self.tasks[work['id']] = work
        pin = dict(self.host.context['plan'])
        family = {'plan': pin}
        self.record['clips']['A']['sectionFamilies'] = [family]
        self.free(1)
        missing = str(Path(pin['path']).with_name('TEST-missing-plan.json'))
        cases = (({'path': missing}, 'FileNotFoundError'), ({'sha256': 'f' * 64}, 'artifact bytes changed'))
        for change, text in cases:
            with self.subTest(text):
                family['plan'] = {**pin, **change}
                before = copy.deepcopy(self.record)
                self.assertRegex(self.claimed(work), rf"^AI task TEST-run-scoped is refused: clip A's current section "
                                                     rf"family plan cannot be read or verified \(.*{text}")
                self.assertEqual(before, self.record)
        family['plan'] = pin
        self.assertEqual(self.claimed(work), 'claimed')


if __name__ == '__main__':
    unittest.main()
