"""M-052 (C-2, X121, X144, X159): the job identity, the recorded duplication check, its decision line, and what
status, replays and the add-clip command show.

The job identity is the folded title (NFC, casefold, no format characters, collapsed whitespace), the source and the
ordered kept words; range grouping, seconds and transcript bytes are not the job. The check is one value carried on
the clip's adding event: clip-id ordered rows with the overlap to the millisecond. A replay answers the recorded
value, never a recomputed one. A decision line the trail refuses after the add committed never fails the add or
status: it stays a pending decision, reported under ``pendingDecisions``, until a later add, replay or status writes
it once (a full trail or a closed batch keeps it pending). An adding event with no check shows no key in status.

Authority tests use real private files and kernel locks under a temporary root; every approval is a TEST fixture.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _budget_fixture import approval, source_sha, transcript_words
from _dispatch_fixture import approval_file
from test_native_budget_registry import ns
from test_production_add_clip_clock import SAME_JOB, AddClipCase, row, script
import native_batch
from studio import native_budget_registry as registry
from studio.native_budget_store import MAX_EVENT_BYTES, TERMINAL_RESERVE_BYTES, BatchSession, BudgetAuthorityError
from studio.production.duplication_check import duplication_check

FULL = 'Budget event trail is full: no new work is admitted; close the batch'


def cut(title: str, first: int, last: int, seconds: tuple[tuple[float, float], ...]) -> object:
    """A TEST approval of the words ``first``-39 and 50-``last``, cut at the explicit ``seconds``."""
    return approval('X', title=title, **{**script(first, 39, (50, last)), 'ranges': seconds})


class JobIdentityTests(AddClipCase):
    """X159: title fold, source and ordered kept words; how the words are cut or stored is not the job."""

    def refused_as_a(self, value: object) -> None:
        """``value`` added under a new id is refused as clip A's job, and nothing is added."""
        with self.assertRaisesRegex(registry.BudgetRefused, SAME_JOB.format('A')):
            self.add('X', value)
        self.assertNotIn('X', self.record()['clips'])

    def test_a_split_word_range_keeps_the_same_job(self) -> None:
        """MAJOR-2: A's words with one range split at a word boundary are A's job."""
        self.refused_as_a(approval('A', word_ranges=((10, 20), (21, 39), (50, 79)),
                                   ranges=((10.0, 21.0), (21.0, 40.0), (50.0, 80.0))))

    def test_format_characters_case_and_spacing_fold_into_the_same_title(self) -> None:
        """U+200B, U+00AD, a case-only retitle and extra spaces all fold to A's title."""
        for title in ('TEST title A\u200b', 'TEST ti\u00adtle A', 'test TITLE a', ' TEST  Title\tA '):
            with self.subTest(title=title):
                self.refused_as_a(approval('A', title=title))

    def test_a_reserialized_transcript_with_the_same_kept_words_is_the_same_job(self) -> None:
        """The transcript's bytes are not the job: 50 words per utterance instead of 100, the same words."""
        words = transcript_words()
        data = json.dumps({'transcript': [{'words': words[start:start + 50]} for start in range(0, len(words), 50)]})
        path = self.work / 'same-words-other-bytes.json'
        path.write_text(data)
        self.refused_as_a(approval('A', transcript_path=str(path),
                                   transcript_sha256=hashlib.sha256(data.encode()).hexdigest()))

    def test_another_source_a_reordered_script_or_a_new_title_is_another_job(self) -> None:
        """The same words of another recording, A's words in another order, and a real new title are distinct jobs."""
        other = self.add('X', approval('A', source_sha256=source_sha(b'another-recording')))
        texts = tuple(f'w{index}' for index in (*range(50, 80), *range(10, 40)))
        reordered = self.add('Y', approval('A', word_ranges=((50, 79), (10, 39)), word_texts=texts,
                                           ranges=((50.0, 80.0), (10.0, 40.0))))
        retitled = self.add('Z', approval('A', title='TEST a genuinely new title'))
        self.assertEqual((other['duplicationCheck'], reordered['duplicationCheck'], retitled['duplicationCheck']),
                         (None, [row('A', 60.0, 'different', 'same')],
                          [row('A', 60.0, 'same', 'different'), row('Y', 60.0, 'different', 'different')]))


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
        record = self.record()                                     # the store reads clips back in key order,
        record['clips'] = dict(reversed(list(record['clips'].items())))   # so the order is pinned in memory too
        self.assertEqual(duplication_check(record, 'Q', record['clips']['Q']), added['duplicationCheck'])

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
    """X144 minor 1, X159 D2/D3: a refused decision line never fails an add or status; it stays pending until
    written once."""

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

    def test_every_owed_line_is_written_not_only_the_latest(self) -> None:
        """T's and U's lines are both refused; the next status writes both and reports nothing pending."""
        with self.refuse_decisions():
            self.add('T', approval('T', title='TEST trim of A', **script(12, 39, (50, 79))))
            owed = self.add('U', approval('U', title='TEST other trim of A', **script(10, 39, (50, 77))))
        self.assertEqual(len(owed['pendingDecisions']), 2)                   # U's add retried T's line too
        status = native_batch.cmd_status(ns(batch='batch-auth'))
        self.assertEqual((status['pendingDecisions'], sorted(line['outputId'] for line in self.trail(
            'coordination-decision'))), ([], ['T', 'U']))

    def test_a_full_trail_keeps_the_line_pending_and_status_never_fails(self) -> None:
        """D2 (X159): the trail cap has no exception; status keeps reporting the owed line and never raises."""
        with self.refuse_decisions():
            self.add('T', approval('T', title='TEST trim of A', **script(12, 39, (50, 79))))
        pending = {'decisionId': 'duplication-check.' + self.trail('clip-added')[-1]['approval'][:32], 'outputId': 'T'}
        events = self.root / 'batches/batch-auth/events.jsonl'
        room = MAX_EVENT_BYTES - TERMINAL_RESERVE_BYTES - 300 - events.stat().st_size   # status fits, a decision not
        prefix = json.dumps({'event': 'test-padding', 'pad': ''}) + '\n'
        with events.open('a') as handle:
            handle.write(json.dumps({'event': 'test-padding', 'pad': 'x' * (room - len(prefix))}) + '\n')
        for _ in range(2):                                          # a real refusal each time, never an error
            self.assertEqual(native_batch.cmd_status(ns(batch='batch-auth'))['pendingDecisions'], [pending])
        self.assertEqual((self.trail('coordination-decision'), self.trail('clip-added')[-1]['duplicationCheck']),
                         ([], [row('A', 58.0, 'different', 'different')]))       # the check survives on its event

    def test_a_closed_batch_takes_no_line_and_status_keeps_it_pending(self) -> None:
        """A batch that closes first takes no decision line (P3a); status still names the pending decision."""
        with self.refuse_decisions():
            self.add('T', approval('T', title='TEST trim of A', **script(12, 39, (50, 79))))
        self.clock.advance(3000)
        native_batch.cmd_close(ns(batch='batch-auth'))
        status = native_batch.cmd_status(ns(batch='batch-auth'))
        self.assertEqual((status['status'], [row['outputId'] for row in status['pendingDecisions']],
                          self.trail('coordination-decision')), ('closed', ['T'], []))

    def test_add_clip_command_answers_deadline_replay_check_and_pending(self) -> None:
        """D3 (X159): native_batch.py add-clip shows its own deadline, replay, recorded check and pending lines."""
        file = approval_file(self.work, 'T', approval('T', title='TEST trim of A', **script(12, 39, (50, 79))))
        self.clock.advance(300)
        with self.refuse_decisions():
            first = native_batch.cmd_add_clip(ns(batch='batch-auth', clip='T', reason='TEST operator', approval=file))
        again = native_batch.cmd_add_clip(ns(batch='batch-auth', clip='T', reason='TEST operator', approval=file))
        self.assertEqual((first['replayed'], first['deadlineElapsed'], first['duplicationCheck'],
                          [line['refusal'] for line in first['pendingDecisions']]),
                         (False, 2700.0, [row('A', 58.0, 'different', 'different')], [FULL]))
        self.assertEqual((again['replayed'], again['deadlineElapsed'], again['pendingDecisions']), (True, 2700.0, []))


if __name__ == '__main__':
    unittest.main()
