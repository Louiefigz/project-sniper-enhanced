"""Schema 8's version and lift guards (P1 review point 1, X180): what a read refuses before it lifts or validates.

m1 the next version; m2 which row kinds take optional keys; m3 the A5 shape by key; m4 a 5-7 record carrying
content only schema 8 writes (``native_budget_lift.newer_content_problem``); m5 an integer too large for a float.
Every root is private; records are this engine's TEST records, written raw.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import itertools
import re
import unittest

from _budget_fixture import FakeClock, fake_clock, private_root
from studio.native_budget_batches import create_batch
from studio.native_budget_schema import OPTIONAL_ROWS, SCHEMA_VERSION, a5_shape, validate_record
from studio.native_budget_store import BudgetAuthorityError, read_batch
from test_budget_schema_shapes import A5_REFUSAL, STORAGE, d1_schema_five, delivered
from test_queue_clock_v2 import BATCH, short_record, write_raw

# (the refusal's name for it, where it sits, its key, its value): content only schema 8 writes (P1-RP1 m4).
NEWER = (('production.storage', ('production',), 'storage', STORAGE),
         ('production.closure', ('production',), 'closure', {'closedElapsed': 1.0, 'unresolvedAtClose': []}),
         ('A.attempts.admittedForecastSeconds', ('clips', 'A', 'attempts', 0), 'admittedForecastSeconds', 1.0),
         ('A.attempts.late', ('clips', 'A', 'attempts', 0), 'late', True),
         ('A.deliveries.late', ('clips', 'A', 'deliveries', 0), 'late', True),
         ('A.capacityClock v2', ('clips', 'A'), 'capacityClock', short_record()['clips']['A']['capacityClock']))


def put(record: dict, path: tuple, key: str, value: object) -> None:
    """Set ``key`` to a copy of ``value`` in the mapping at ``path``."""
    target = record
    for step in path:
        target = target[step]
    target[key] = copy.deepcopy(value)


class LiftGuardTests(unittest.TestCase):
    """Each refusal is by name, before any lift, and the record's bytes are left as they were."""

    def setUp(self) -> None:
        """A private root holding this engine's record (a v1 clock, the P0 engine's shape); fixed TEST clocks."""
        self.enterContext(fake_clock(FakeClock()))
        self.root = private_root(self)
        create_batch(self.root, delivered())

    def refused(self, record: dict, pattern: str) -> None:
        """Write ``record`` raw; its read is refused with ``pattern`` and leaves the bytes unchanged."""
        write_raw(self.root, record)
        before = (self.root / 'batches' / BATCH / 'authority.json').read_bytes()
        with self.assertRaisesRegex(BudgetAuthorityError, pattern):
            read_batch(self.root, BATCH)
        self.assertEqual((self.root / 'batches' / BATCH / 'authority.json').read_bytes(), before)

    def test_the_next_version_is_refused_by_name(self) -> None:
        """m1: V+1 (and any unknown version) is the named version refusal on a raw read."""
        for version in (SCHEMA_VERSION + 1, 99):
            with self.subTest(version=version):
                self.refused({**delivered(), 'schemaVersion': version},
                             f'written by another engine version \\(schemaVersion {version}, this engine 8\\)')

    def test_only_attempts_and_deliveries_take_optional_keys(self) -> None:
        """m2 (W2-D6): other row kinds behave exactly as before; ``late`` on a dispatch, hold or project row fails."""
        self.assertEqual(set(OPTIONAL_ROWS), {'attempt', 'delivery'})
        rows = {'dispatches': {'kind': 'author', 'label': 'TEST dispatch', 'elapsed': 5.0},
                'holds': {'startElapsed': 5.0, 'endElapsed': 6.0, 'reason': 'TEST hold'},
                'projects': {'key': 'c' * 64, 'path': '/TEST/other-project', 'projectHash': None,   # a Short's project
                             'selection': {'source': 'e' * 64, 'ranges': [[0.0, 10.0]]}}}          # carries its cut
        for name, row in rows.items():
            record = delivered()
            target = record if name == 'holds' else record['clips']['A']
            target[name] = [*target[name], dict(row)]
            validate_record(record)
            target[name][-1]['late'] = True
            with self.subTest(name), self.assertRaisesRegex(ValueError, 'budget record is invalid'):
                validate_record(record)

    def test_a5_shape_is_the_key_not_its_value(self) -> None:
        """m3 (P4-LONG:484): an attempt carrying ``forecast: None`` is still the A5 shape."""
        old = d1_schema_five(delivered())
        old['clips']['A']['attempts'][0]['forecast'] = None
        self.assertTrue(a5_shape(old))
        self.refused(old, f'^{re.escape(A5_REFUSAL)}$')

    def test_a_lifted_record_with_v8_only_content_is_refused(self) -> None:
        """m4: a record claiming 5-7 that carries content only schema 8 writes is refused by name, never lifted."""
        self.assertEqual(NEWER[-1][3]['policy'], 'short-render-capacity-v2')
        for (name, path, key, value), version in itertools.product(NEWER, (5, 6, 7)):
            record = {**delivered(), 'schemaVersion': version}
            put(record, path, key, value)
            with self.subTest(name, version=version):
                self.refused(record, f'claims schema {version} but carries content only schema 8 writes '
                                     f'\\({re.escape(name)}\\); it is refused, never lifted')

    def test_a_huge_integer_is_an_unreadable_record(self) -> None:
        """m5: an integer too large for a float is refused as unreadable, never raised as an OverflowError."""
        record = delivered()
        record['clips']['A']['capacityClock']['excludedSeconds'] = 10 ** 400
        self.refused(record, 'unreadable or corrupt: budget record is invalid: '
                             'unreadable structure \\(OverflowError\\)')


if __name__ == '__main__':
    unittest.main()
