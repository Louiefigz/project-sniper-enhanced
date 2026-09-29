"""The host-level unresolved-execution record (X37, M-043): append-only, fail closed, on a private root."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import os
import stat
import unittest
from unittest.mock import patch

from studio import native_budget_store
from studio.native_budget_store import BudgetAuthorityError
from studio.production import unresolved_executions as host_record
from studio.production.unresolved_executions import Execution, append_unresolved, open_rows, recorded_task_ids, resolve

EVIDENCE = {'basis': 'process-absent', 'detail': 'pid 4242 started 20:00:00 is absent by R1 identity; no descendant'}
PROCESS = {'pid': 4242, 'pgid': 4242, 'started': 'Mon Sep 28 20:00:00 2026'}


def closure_row(task_id: str, kind: str = 'author', host: str | None = 'claude-code', **fields: object) -> dict:
    """One ``production.closure.unresolvedAtClose`` row as M-043 writes it."""
    row = {'taskId': task_id, 'kind': kind, 'state': 'completed', 'host': host, 'hostProcess': None,
           'reason': 'the host ended this turn; no end event identifies the execution'}
    row.update(fields)
    return row


class HostRecordTests(unittest.TestCase):
    """Rows are written at closure, charged per host until evidence resolves them, and never rewritten."""

    def setUp(self) -> None:
        """This test's private budget root and the record's path under it."""
        self.root = native_budget_store.default_root()
        self.path = self.root / host_record.RECORD

    def _bytes(self) -> bytes:
        """The record's current bytes."""
        return self.path.read_bytes()

    def test_rows_stay_open_until_evidence_resolves_them(self) -> None:
        """Open rows are listed per host; a resolution closes one row once; a second resolution changes nothing."""
        rows = [closure_row('author-1'), closure_row('review-1', 'review', 'codex'),
                closure_row('media-1', 'media', None)]
        self.assertEqual(append_unresolved(self.root, 'batch-one', rows), 3)
        self.assertEqual([row['taskId'] for row in open_rows(self.root, 'claude-code')], ['author-1'])
        self.assertEqual(open_rows(self.root, 'codex')[0], {'schema': 1, 'event': 'execution-unresolved',
                                                           'batchId': 'batch-one', **rows[1]})
        self.assertTrue(resolve(self.root, Execution('batch-one', 'author-1'), EVIDENCE))
        self.assertEqual(open_rows(self.root, 'claude-code'), [])
        self.assertFalse(resolve(self.root, Execution('batch-one', 'author-1'), EVIDENCE))
        self.assertEqual(recorded_task_ids(self.root, 'batch-one'), {'author-1', 'review-1', 'media-1'})
        self.assertEqual(recorded_task_ids(self.root, 'batch-two'), frozenset())

    def test_record_is_append_only_private_and_outside_the_batches(self) -> None:
        """Every write keeps the earlier bytes as a prefix; the file is 0600 at the root, beside batches/."""
        append_unresolved(self.root, 'batch-one', [closure_row('author-1')])
        first = self._bytes()
        append_unresolved(self.root, 'batch-two', [closure_row('author-1', hostProcess=dict(PROCESS))])
        second = self._bytes()
        resolve(self.root, Execution('batch-two', 'author-1'), EVIDENCE)
        third = self._bytes()
        self.assertTrue(second.startswith(first) and third.startswith(second) and len(third) > len(second) > len(first))
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(self.path.parent, self.root)
        self.assertTrue((self.root / 'batches').is_dir() and (self.root / 'archive').is_dir())

    def test_a_retried_closure_appends_nothing_twice(self) -> None:
        """An execution already recorded, open or resolved, is never appended again (no double charge)."""
        rows = [closure_row('author-1'), closure_row('review-1', 'review')]
        append_unresolved(self.root, 'batch-one', rows)
        resolve(self.root, Execution('batch-one', 'author-1'), EVIDENCE)
        before = self._bytes()
        self.assertEqual(append_unresolved(self.root, 'batch-one', rows), 0)
        self.assertEqual(self._bytes(), before)
        self.assertEqual([row['taskId'] for row in open_rows(self.root, 'claude-code')], ['review-1'])
        self.assertEqual(append_unresolved(self.root, 'batch-one', [*rows, closure_row('check-1', 'check', None)]), 1)

    def test_rows_are_checked_before_anything_is_written(self) -> None:
        """A malformed closure is refused whole, and no file is created."""
        bad = [[closure_row('author-1', host=None)], [closure_row('author-1', host='gemini')],
               [closure_row('author-1', hostProcess={'type': 'process', **PROCESS})],
               [closure_row('author-1', hostProcess={'pid': 0, 'pgid': 1, 'started': 'x'})],
               [closure_row('author-1', kind='painter')], [closure_row('author-1', state='done')],
               [closure_row('author-1', reason='x' * 513)], [{**closure_row('author-1'), 'batchId': 'batch-one'}],
               [closure_row('author-1'), closure_row('author-1')], [closure_row('bad id')]]
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                append_unresolved(self.root, 'batch-one', rows)
        with self.assertRaises(ValueError):
            append_unresolved(self.root, 'Batch One', [closure_row('author-1')])
        self.assertFalse(self.path.exists())

    def test_an_operator_statement_is_never_evidence(self) -> None:
        """Only a G9 basis resolves a row, and only a recorded execution can be resolved."""
        append_unresolved(self.root, 'batch-one', [closure_row('author-1')])
        before = self._bytes()
        for evidence in ({'basis': 'operator-statement', 'detail': 'I stopped it'}, {'basis': 'host-end', 'detail': ''},
                         {'basis': 'host-end'}, {'basis': 'host-end', 'detail': 'x' * 513}, None):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                resolve(self.root, Execution('batch-one', 'author-1'), evidence)
        with self.assertRaisesRegex(ValueError, 'No unresolved execution'):
            resolve(self.root, Execution('batch-one', 'author-9'), EVIDENCE)
        self.assertEqual(self._bytes(), before)
        self.assertEqual(len(open_rows(self.root, 'claude-code')), 1)
        with self.assertRaises(ValueError):
            open_rows(self.root, 'gemini')

    def test_a_corrupt_torn_or_inconsistent_record_refuses_every_read(self) -> None:
        """Unreadable means refuse: garbage, a torn line, another schema, a repeated row or resolution, or a
        resolution with no row makes admission and closure fail closed instead of guessing."""
        append_unresolved(self.root, 'batch-one', [closure_row('author-1'), closure_row('author-2')])
        resolve(self.root, Execution('batch-one', 'author-1'), EVIDENCE)
        good = self._bytes()
        row_line, _, resolution_line = good.splitlines(keepends=True)
        unknown = resolution_line.replace(b'"taskId":"author-1"', b'"taskId":"author-3"')
        tails = [b'not json\n', b'{"schema":1}', b'{"schema":2,"event":"execution-unresolved"}\n', row_line,
                 resolution_line, unknown]
        for tail in tails:
            with self.subTest(tail=tail):
                self.path.write_bytes(good + tail)
                self._assert_every_read_refused()

    def _assert_every_read_refused(self) -> None:
        """Listing, the archive lookup and a new closure all refuse the record."""
        reads = (lambda: open_rows(self.root, 'claude-code'), lambda: recorded_task_ids(self.root, 'batch-one'),
                 lambda: append_unresolved(self.root, 'batch-two', [closure_row('author-1')]))
        for read in reads:
            with self.assertRaises(BudgetAuthorityError):
                read()

    def test_a_full_record_refuses_new_rows_but_still_takes_resolutions(self) -> None:
        """New rows stop at the reserve, so evidence can always resolve what is already charged."""
        append_unresolved(self.root, 'batch-one', [closure_row('author-1')])
        size = len(self._bytes())
        with patch.object(host_record, 'MAX_RECORD_BYTES', size + 400), \
                patch.object(host_record, 'RESOLUTION_RESERVE_BYTES', 400):
            with self.assertRaisesRegex(BudgetAuthorityError, 'full'):
                append_unresolved(self.root, 'batch-two', [closure_row('author-1')])
            self.assertTrue(resolve(self.root, Execution('batch-one', 'author-1'), EVIDENCE))
        self.assertEqual(recorded_task_ids(self.root, 'batch-two'), frozenset())


if __name__ == '__main__':
    unittest.main()
