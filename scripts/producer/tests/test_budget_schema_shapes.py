"""The release's record shapes (P4-06, carried by M-044): the lifts, the A5 refusal and the optional P4 fields.

The D1 and A5 schema-5 records are built here from this engine's record; every root is private.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import re
import unittest

from _budget_fixture import FakeClock, fake_clock, private_root
from studio.native_budget_batches import archive_batch, create_batch
from studio.native_budget_schema import SCHEMA_VERSION, a5_shape, validate_record
from studio.native_budget_store import BudgetAuthorityError, canonical, read_batch
from studio.production.production_optional import PRODUCTION_OPTIONAL, VALIDATORS
from studio.production.task_schema import PRODUCTION_KEYS
from test_queue_clock_v2 import BATCH, OWNER, V1_CLOCK, add_tasks, short_record, write_raw

A5_REFUSAL = ('Schema 5 record written by an A5-forecast build (attempts carry a forecast field): this engine reads '
              'only the D1 schema-5 shape. Finish that batch with the engine that wrote it, or archive it once closed.')
ATTEMPT = {'id': 'a' * 32, 'route': 'draft', 'project': '/TEST/project', 'output': '/TEST/output', 'identity': 'b' * 64,
           'admittedElapsed': 30.0, 'outputSeconds': 45.6, 'grantedSeconds': 900.0,
           'supervisor': {'pid': 7001, 'pgid': 7001, 'started': OWNER['started']}, 'status': 'succeeded',
           'resultStatus': 'TEST checked', 'failure': None, 'completedElapsed': 400.0, 'stages': [], 'nested': {},
           'transientRetryOf': None}
DELIVERY = {'kind': 'draft', 'output': '/TEST/output/draft.mp4', 'sha256': 'd' * 64, 'attemptId': 'a' * 32,
            'elapsed': 410.0}


def delivered(clock: dict | None = V1_CLOCK) -> dict:
    """This engine's record with one delivered draft attempt for A and two task rows."""
    record = short_record(clock)
    clip = record['clips']['A']
    clip['attempts'], clip['deliveries'] = [dict(ATTEMPT)], [dict(DELIVERY)]
    clip['counters']['exportAttempt'] = 1
    add_tasks(record)
    return record


def d1_schema_five(record: dict) -> dict:
    """The D1 schema-5 shape: no capacity clock, no section history, the authorization and task rows before the
    fields ``lift_additive_fields`` supplies."""
    old = {**copy.deepcopy(record), 'schemaVersion': 5}
    for clip in old['clips'].values():
        clip.pop('capacityClock', None)
    authorization = old['production']['authorization']
    del authorization['prior'], authorization['priorOmitted']
    for row in old['production']['tasks'].values():
        del row['owners'], row['revoked']
    return old


class BudgetSchemaShapeTests(unittest.TestCase):
    """Private roots and fixed TEST clocks; every record is read back through the store's lock and validator."""

    def setUp(self) -> None:
        """A private root holding one published batch; no clock reads the host."""
        self.enterContext(fake_clock(FakeClock()))
        self.root = private_root(self)
        self.record = delivered()
        create_batch(self.root, self.record)

    def test_d1_v5_lifts(self) -> None:
        """A D1 schema-5 record reads as the new version; only the old schema's implicit fields are added."""
        old = d1_schema_five(self.record)
        self.assertFalse(a5_shape(old))
        write_raw(self.root, old)
        expected = copy.deepcopy(old)
        expected['schemaVersion'] = SCHEMA_VERSION
        expected['production']['authorization'].update(prior=[], priorOmitted=0)
        for row in expected['production']['tasks'].values():
            row.update(owners=[], revoked=False)
        self.assertEqual(canonical(read_batch(self.root, BATCH)), canonical(expected))

    def test_a5_v5_refused_by_name(self) -> None:
        """An A5-forecast schema-5 record (an attempt carries ``forecast``) is refused with the exact text."""
        old = d1_schema_five(self.record)
        old['clips']['A']['attempts'][0]['forecast'] = {'forecastSeconds': 300.0}
        self.assertTrue(a5_shape(old))
        write_raw(self.root, old)
        with self.assertRaises(BudgetAuthorityError) as caught:
            read_batch(self.root, BATCH)
        self.assertEqual(str(caught.exception), A5_REFUSAL)
        write_raw(self.root, {**old, 'schemaVersion': 6})   # only a schema-5 record is read as the A5 shape
        with self.assertRaisesRegex(BudgetAuthorityError, 'unreadable or corrupt: .*clip attempts'):
            read_batch(self.root, BATCH)
        # Closed, with its tasks ended, the refused A5 batch leaves resolution as the message says.
        write_raw(self.root, {**old, 'status': 'closed', 'closedAtElapsed': 500.0,
                              'production': {**old['production'], 'tasks': {}}})
        archive_batch(self.root, BATCH, 'TEST operator archived an A5-forecast batch')
        self.assertTrue((self.root / 'archive' / BATCH / 'authority.json').is_file())

    def test_v7_lifts_to_next_without_field_changes(self) -> None:
        """A version-7 record reads as the next version and nothing else changes."""
        v7 = {**copy.deepcopy(self.record), 'schemaVersion': 7}
        write_raw(self.root, v7)
        lifted = read_batch(self.root, BATCH)
        self.assertEqual((SCHEMA_VERSION, lifted['schemaVersion']), (8, 8))
        self.assertEqual(canonical({**lifted, 'schemaVersion': 7}), canonical(v7))

    def test_admitted_forecast_and_late_fields_validate(self) -> None:
        """The optional attempt and delivery fields validate when present, and are never required."""
        record = delivered(None)
        validate_record(record)
        clip = record['clips']['A']
        for forecast in (0, 12.5, 900):
            clip['attempts'][0].update(admittedForecastSeconds=forecast, late=True)
            clip['deliveries'][0]['late'] = True
            validate_record(record)
        for forecast in (-1, float('nan'), float('inf'), True, '12'):
            clip['attempts'][0]['admittedForecastSeconds'] = forecast
            with self.subTest(forecast=forecast), self.assertRaisesRegex(ValueError, 'clip attempts'):
                validate_record(record)
        del clip['attempts'][0]['admittedForecastSeconds']
        clip['attempts'][0]['lateness'] = True
        with self.assertRaisesRegex(ValueError, 'clip attempts'):
            validate_record(record)

    def test_forged_late_value_refused(self) -> None:
        """``late`` is only the literal True, on an attempt or a delivery."""
        cases = [(kind, value) for kind in ('attempts', 'deliveries') for value in (False, 'yes', 1, None)]
        for kind, value in cases:
            record = delivered(None)
            record['clips']['A'][kind][0]['late'] = value
            with self.subTest(kind=kind, late=value), self.assertRaisesRegex(ValueError, f'clip {kind}'):
                validate_record(record)


class NoDefaultTests(unittest.TestCase):
    """X50: an absent required field is refused at every seam, never defaulted (the ledger's opt rows aside)."""

    def setUp(self) -> None:
        """A private root holding this engine's version-8 record."""
        self.enterContext(fake_clock(FakeClock()))
        self.root = private_root(self)
        self.record = delivered(None)
        create_batch(self.root, self.record)

    def test_a_row_or_the_production_block_missing_a_required_key_is_refused(self) -> None:
        """A required attempt, delivery or production key cannot be left out, even beside the optional ones."""
        cases = [(('clips', 'A', 'attempts', 0), 'status', 'clip attempts'),
                 (('clips', 'A', 'deliveries', 0), 'elapsed', 'clip deliveries'),
                 (('production',), 'drain', 'production block fields')]
        for path, key, text in cases:
            record = copy.deepcopy(self.record)
            target = record
            for step in path:
                target = target[step]
            del target[key]
            with self.subTest(key), self.assertRaisesRegex(ValueError, f'budget record is invalid: {text}$'):
                validate_record(record)

    def test_a_version_8_record_gains_no_implicit_field(self) -> None:
        """The lift's implicit fields exist for versions 5-7 only: a version-8 record without them is refused,
        and the read rewrites nothing."""
        strips = {'task owners': lambda record: record['production']['tasks']['author-1'].pop('owners'),
                  'prior authorizations': lambda record: record['production']['authorization'].pop('prior')}
        for name, strip in strips.items():
            record = copy.deepcopy(self.record)
            strip(record)
            write_raw(self.root, record)
            before = (self.root / 'batches' / BATCH / 'authority.json').read_bytes()
            with self.subTest(name), self.assertRaisesRegex(BudgetAuthorityError, 'unreadable or corrupt'):
                read_batch(self.root, BATCH)
            self.assertEqual((self.root / 'batches' / BATCH / 'authority.json').read_bytes(), before)


GIB = 1024 ** 3
STORAGE = {'ceilingBytes': 200 * GIB, 'minimumFreeBytes': 10 * GIB, 'basis': 'computed-default'}
STORAGE_TEXT = {'keys': 'production.storage must hold exactly ceilingBytes, minimumFreeBytes and basis',
                'bytes': 'production.storage ceilingBytes and minimumFreeBytes must be positive whole byte counts',
                'basis': 'production.storage basis must be computed-default or operator-statement'}
STORAGE_VIOLATIONS = (
    ('not a mapping', [STORAGE], 'keys'),
    ('no basis', {'ceilingBytes': 1, 'minimumFreeBytes': 1}, 'keys'),
    ('an unknown key', {**STORAGE, 'reserveFactor': 2}, 'keys'),
    ('zero bytes', {**STORAGE, 'ceilingBytes': 0}, 'bytes'),
    ('negative bytes', {**STORAGE, 'minimumFreeBytes': -1}, 'bytes'),
    ('fractional bytes', {**STORAGE, 'ceilingBytes': 1.5}, 'bytes'),
    ('boolean bytes', {**STORAGE, 'ceilingBytes': True}, 'bytes'),
    ('unbounded bytes', {**STORAGE, 'ceilingBytes': 10 ** 15 + 1}, 'bytes'),
    ('unknown basis', {**STORAGE, 'basis': 'guess'}, 'basis'),
)


class ProductionOptionalTests(unittest.TestCase):
    """The production block's optional keys (W2-D3, W2-D4): absent is valid, present is validated, never defaulted."""

    def setUp(self) -> None:
        """No test reads the host's clocks."""
        self.enterContext(fake_clock(FakeClock()))

    def test_storage_is_optional_and_round_trips(self) -> None:
        """A record without ``storage`` is valid; either basis is accepted and survives a write and a read."""
        self.assertEqual((PRODUCTION_OPTIONAL, set(VALIDATORS)), ({'storage', 'closure'}, {'storage', 'closure'}))
        self.assertEqual(PRODUCTION_KEYS, {'ai', 'drain', 'tasks', 'governance', 'authorization'})
        record = short_record()
        validate_record(record)
        record['production']['storage'] = {**STORAGE, 'basis': 'operator-statement'}
        validate_record(record)
        record['production']['storage'] = dict(STORAGE)
        root = private_root(self)
        create_batch(root, record)
        self.assertEqual(read_batch(root, BATCH)['production']['storage'], STORAGE)

    def test_storage_violations_are_refused_by_name(self) -> None:
        """Keys, positive bounded whole bytes and the two bases, each refused with its own text."""
        record = short_record()
        for name, value, text in STORAGE_VIOLATIONS:
            record['production']['storage'] = value
            exact = f'^{re.escape("budget record is invalid: " + STORAGE_TEXT[text])}$'
            with self.subTest(name), self.assertRaisesRegex(ValueError, exact):
                validate_record(record)

    def test_closure_is_refused_until_its_validator_lands(self) -> None:
        """``closure`` is a fixed key refused by name before M-043; any other extra key is not a production key."""
        record = short_record()
        record['production']['closure'] = {'closedElapsed': 10.0, 'unresolvedAtClose': []}
        refusal = 'budget record is invalid: production.closure is not accepted until its validator lands (M-043)'
        with self.assertRaisesRegex(ValueError, f'^{re.escape(refusal)}$'):
            validate_record(record)
        del record['production']['closure']
        record['production']['extra'] = None
        with self.assertRaisesRegex(ValueError, 'production block fields$'):
            validate_record(record)


if __name__ == '__main__':
    unittest.main()
