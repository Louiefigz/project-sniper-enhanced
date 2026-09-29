"""M-052 (C-2, X121, X144): the recorded duplication check, its decision line, and what status and replays show.

The check is one value carried on the clip's adding event: clip-id ordered rows with the overlap to the
millisecond. A replay answers the recorded value, never a recomputed one. A decision line the trail refuses after
the add committed never fails the add: the add names it as pending, and the next status or retry writes it once.
An adding event that carries no check shows no key in status (X50: absent is not "no overlap").

Authority tests use real private files and kernel locks under a temporary root; every approval is a TEST fixture.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _budget_fixture import approval
from test_native_budget_registry import ns
from test_production_add_clip_clock import AddClipCase, row, script
import native_batch
from studio.native_budget_store import BatchSession, BudgetAuthorityError

FULL = 'Budget event trail is full: no new work is admitted; close the batch'


def cut(title: str, first: int, last: int, seconds: tuple[tuple[float, float], ...]) -> object:
    """A TEST approval of the words ``first``-39 and 50-``last``, cut at the explicit ``seconds``."""
    return approval('X', title=title, **{**script(first, 39, (50, last)), 'ranges': seconds})


class RecordedCheckTests(AddClipCase):
    """X121's shape: rows in clip-id order, overlap to the millisecond; the recorded value is the only answer."""

    def test_rows_are_in_clip_id_order_with_millisecond_overlap(self) -> None:
        """Z then K are added (record order), so Q's rows must still read A, K, Z, each to the millisecond."""
        self.add('Z', approval('Z', title='TEST Z', **script(12, 39, (50, 79))))
        self.add('K', approval('K', title='TEST K', **script(10, 39, (50, 77))))
        added = self.add('Q', cut('TEST Q', 11, 79, ((11.0, 39.937), (50.0, 79.937))))
        self.assertEqual(added['duplicationCheck'], [row('A', 58.874, 'different', 'different'),
                                                     row('K', 56.937, 'different', 'different'),
                                                     row('Z', 57.874, 'different', 'different')])

    def test_a_replay_answers_the_recorded_check_never_a_fresh_one(self) -> None:
        """X144 minor 2: U is added after T and overlaps it; T's replay still answers T's recorded check."""
        trim = approval('T', title='TEST trim of A', **script(12, 39, (50, 79)))
        first = self.add('T', trim)
        self.add('U', approval('U', title='TEST other trim of A', **script(10, 39, (50, 77))))
        again = self.add('T', trim)
        status = native_batch.cmd_status(ns(batch='batch-auth'))['clips']['T']['duplicationCheck']
        self.assertEqual((again['replayed'], again['duplicationCheck'], status),
                         (True, first['duplicationCheck'], first['duplicationCheck']))
        self.assertEqual([item['clip'] for item in first['duplicationCheck']], ['A'])

    def test_the_check_is_read_from_the_committed_adding_event(self) -> None:
        """A killed add leaves an adding event the record never took; the retry's (last) event is the recorded one."""
        trim = approval('T', title='TEST trim of A', **script(12, 39, (50, 79)))
        with mock.patch('studio.native_budget_store.write_pending_replace', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.add('T', trim)                                 # its event names A only
        self.add('U', approval('U', title='TEST other trim of A', **script(10, 39, (50, 77))))
        retried = self.add('T', trim)
        status = native_batch.cmd_status(ns(batch='batch-auth'))['clips']['T']['duplicationCheck']
        self.assertEqual([[item['clip'] for item in check] for check in (retried['duplicationCheck'], status)],
                         [['A', 'U'], ['A', 'U']])

    def test_an_adding_event_without_the_key_shows_no_key(self) -> None:
        """X144 minor 6: a clip-added event written before M-052 (no duplicationCheck) shows no key, never null."""
        self.add('C', approval('C'))
        events = self.root / 'batches/batch-auth/events.jsonl'
        rows = [json.loads(line) for line in events.read_bytes().splitlines()]
        for item in rows:
            if item.get('event') == 'clip-added':
                del item['duplicationCheck']
        events.write_text(''.join(json.dumps(item) + '\n' for item in rows))
        clips = native_batch.cmd_status(ns(batch='batch-auth'))['clips']
        self.assertEqual(['duplicationCheck' in clips[clip] for clip in ('A', 'C')], [False, False])
        self.assertNotIn('duplicationCheck', self.add('C', approval('C')))   # its replay answers none either


class DecisionLineTests(AddClipCase):
    """X144 minor 1: a refused decision line never fails a committed add; the next status or retry writes it once."""

    def refuse_decisions(self) -> object:
        """Refuse every coordination-decision line, as a trail at its reserve would."""
        original = BatchSession.event

        def event(session: BatchSession, value: dict) -> None:
            """The store's append, except that a decision line is refused."""
            if value.get('event') == 'coordination-decision':
                raise BudgetAuthorityError(FULL)
            original(session, value)
        return mock.patch.object(BatchSession, 'event', event)

    def test_a_refused_decision_line_is_pending_and_status_writes_it_once(self) -> None:
        """The add commits and names its pending line; status writes it; a later retry writes nothing more."""
        trim = approval('T', title='TEST trim of A', **script(12, 39, (50, 79)))
        with self.refuse_decisions():
            added = self.add('T', trim)
        pending = 'duplication-check.' + self.trail('clip-added')[-1]['approval'][:32]
        self.assertEqual((added['committed'], added['decisions'], added['pendingDecisions']),
                         (True, [], [{'decisionId': pending, 'refusal': FULL}]))
        self.assertEqual((sorted(self.record()['clips']), self.trail('coordination-decision')), (['A', 'B', 'T'], []))
        for _ in range(2):                                          # the first status writes it; the second nothing
            native_batch.cmd_status(ns(batch='batch-auth'))
        self.assertEqual([line['decisionId'] for line in self.trail('coordination-decision')], [pending])
        again = self.add('T', trim)
        self.assertEqual((again['replayed'], again['decisions'], len(self.trail('coordination-decision'))),
                         (True, [], 1))

    def test_a_retry_writes_the_pending_line_when_status_has_not(self) -> None:
        """The same refused line is written by the add's own retry (a replay) when no status ran in between."""
        trim = approval('T', title='TEST trim of A', **script(12, 39, (50, 79)))
        with self.refuse_decisions():
            self.add('T', trim)
        again = self.add('T', trim)
        self.assertEqual(([line['outputId'] for line in again['decisions']], again['pendingDecisions']), (['T'], []))
        self.assertEqual(len(self.trail('coordination-decision')), 1)


if __name__ == '__main__':
    unittest.main()
