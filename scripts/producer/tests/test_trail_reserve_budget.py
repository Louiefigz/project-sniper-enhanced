"""The event trail's terminal reserve holds every settling line a batch can still owe (X192, X217 M1: X104's "a close
always fits", as a check in code rather than a comment).

The classes are derived from ``TERMINAL_EVENTS`` plus the abandoning ``observed`` line (``native_budget_trail
.terminal``): every class needs a worst case in ``_trail_budget_classes.CLASSES``, so a new settling event cannot
land unbudgeted, and their sum must fit ``TERMINAL_RESERVE_BYTES``. Past ``MAX_EVENT_BYTES - TERMINAL_RESERVE_BYTES``
only these lines are written, so a batch at a full trail can still cancel a stalled Short, settle every task,
record every outcome and close. The bounded writers are checked against their counted widest lines, and every
reader of the trail reads it at ``MAX_EVENT_BYTES`` (or a multiple). Pure arithmetic and source reads; nothing is
written.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import re
import unittest
from pathlib import Path

from _trail_budget_classes import BIG, CLASSES, CLIP, DIGEST, failed_widest, ids, settled_widest
from studio.native_budget_store import canonical
from studio.native_budget_trail import (
    ERROR_TEXT_CHARS, MAX_EVENT_BYTES, TERMINAL_EVENTS, TERMINAL_RESERVE_BYTES, error_text, terminal,
)
from studio.production.queue_authority import _settled_line

STUDIO = Path(__file__).resolve().parents[1] / 'studio'
READ = re.compile(r'read_private_file\([^)]*\bEVENTS\b,\s*([^)]*)\)')


class ReserveBudgetTests(unittest.TestCase):
    """Every settling class has a worst case, their sum fits the reserve, and new work keeps its own room."""

    def test_every_settling_class_has_a_worst_case(self) -> None:
        """The budget's classes are exactly the terminal events and the abandoning observation."""
        self.assertTrue(terminal({'event': 'observed', 'abandoned': ['TEST']}))
        self.assertEqual(set(CLASSES), set(TERMINAL_EVENTS) | {'observed'})

    def test_every_settling_class_fits_the_terminal_reserve(self) -> None:
        """The sum of the classes' worst cases is within TERMINAL_RESERVE_BYTES."""
        rows = {name: bound() for name, bound in CLASSES.items()}
        self.assertTrue(all(type(value) is int and value > 0 for value in rows.values()), rows)
        self.assertLessEqual(sum(rows.values()), TERMINAL_RESERVE_BYTES, rows)

    def test_new_work_keeps_fifteen_mebibytes(self) -> None:
        """Raising the reserve raised the trail bound with it: new work still stops at 15 MiB."""
        self.assertEqual(MAX_EVENT_BYTES - TERMINAL_RESERVE_BYTES, 15 * 1024 ** 2)


class WriterBoundTests(unittest.TestCase):
    """The writers whose lines the budget bounds write no wider line than it counts."""

    def test_an_owner_end_names_owners_by_digest_whatever_their_paths(self) -> None:
        """``capacity-settled`` from a 4 KiB owner path is no wider than the counted line plus its named digests."""
        mark = {'clipId': CLIP, 'worker': '/' + 'w' * 4095, 'state': 'finished', 'elapsed': BIG,
                'excludedSeconds': BIG}
        removed = [f'/{index}' + 'r' * 4000 for index in range(3)]
        line = _settled_line(mark, removed, [], {'capacityState': 'capacity-stalled'})
        self.assertLessEqual(len(canonical(line)), settled_widest() + ids(len(removed), DIGEST))
        self.assertNotIn('worker', line)

    def test_a_failed_commit_line_is_bounded_whatever_the_error(self) -> None:
        """``error_text`` escapes and cuts any error, so a ``commit-failed`` line fits its counted width."""
        text = error_text(OSError('\U0001F600\n"\\' * 10_000))
        self.assertEqual(len(text), ERROR_TEXT_CHARS)
        self.assertTrue(text.isascii() and text.isprintable())
        self.assertLessEqual(len(canonical({'event': 'commit-failed', 'failedEvent': 'capacity-stall-decided',
                                            'error': text})), failed_widest())

    def test_every_reader_reads_the_trail_at_its_bound(self) -> None:
        """Each read of ``events.jsonl`` in studio passes MAX_EVENT_BYTES (or a multiple) as its limit."""
        reads = {path.name: READ.findall(path.read_text()) for path in STUDIO.rglob('*.py')}
        found = {name: limits for name, limits in reads.items() if limits}
        self.assertGreaterEqual(len(found), 4, found)
        for name, limits in found.items():
            self.assertTrue(all('MAX_EVENT_BYTES' in limit for limit in limits), (name, limits))


if __name__ == '__main__':
    unittest.main()
