"""M-122 (P4-02): the Long policy is versioned, and each Long output row keeps the version it froze.

A row is readable only while its policy copy is a version this engine knows: exactly v1 (every Long authorized
before P4), or exactly v2 plus a valid late-delivery mode. A v1 row's deadlines are verified with its own copy, never
with the current policy; a forged or unknown copy is refused by name on every authority read; a new authorization
freezes the current policy. Records are in memory and every approval, clip and recorder is a TEST fixture; each
record is read as the store returns it, through its own serializer (sorted keys, ``native_budget_store.canonical``),
so a check that depended on the literal's key order would fail here. The mixed-forecast admission is stubbed where an
authorization is only the way to write a row: what is written, not whether it fits, is under test here.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _budget_fixture import FakeClock, approval, fake_clock
from studio import native_budget_schema as schema
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_store import canonical
from studio.production import formats, long_policy
from studio.production.long_policy import CURRENT_LONG_POLICY, LONG_POLICY_V1, LONG_POLICY_V2, known_long_policy
from studio.production.outputs import OutputAuthorization, authorize_output

UNKNOWN = r'clip L: Long policy is not a policy version this engine knows \(v1 or v2\)'
# sha256 of the sorted compact JSON of formats.LONG_POLICY at 065e6dff (the pre-P4 policy every v1 row carries).
V1_CANONICAL_SHA256 = 'ef0a38cbe718b5d3d0ad53b5223f45118a94a596de7a201bd07e906acf9e3443'
# A 600 s Long authorized at 0 under v1: 10800 - (600 + 600 + 300 + 120) - (2.9 x 600 + 80) x 1.25.
V1_PREPARATION_600 = 10800.0 - 1620.0 - 2275.0


def run_with_long(seconds: float = 600.0) -> dict:
    """A running TEST batch: Short A on the batch clock and Long L authorized at 0 under the current policy."""
    with fake_clock(FakeClock()):
        record = new_batch_record(BatchSpec('batch-policy', ('A',), (), 1, approvals={'A': approval('A')}),
                                  start_anchor())
    with mock.patch('studio.production.outputs.admission_refusal', return_value=None):
        authorize_output(record, OutputAuthorization('L', 'long', 'TEST Long L', 'TEST operator',
                                                     output_seconds=seconds), 0.0)
    return record


def with_policy(record: dict, policy: object) -> dict:
    """Long L's output row carrying ``policy`` (a deep copy) as its frozen policy copy."""
    record['clips']['L']['output']['policy'] = copy.deepcopy(policy)
    return record


def stored(record: dict) -> dict:
    """``record`` as the store writes and reads it back: sorted keys, compact JSON (the store's ``canonical``)."""
    return json.loads(canonical(record))


def v2_with(late: object) -> dict:
    """The v2 policy with ``late`` as its late-delivery mode."""
    return {**copy.deepcopy(LONG_POLICY_V2), 'lateDelivery': late}


class LongPolicyVersionTests(unittest.TestCase):
    """Rows keep the policy version they froze; only known versions are readable."""

    def test_v1_row_reads_and_verifies_with_its_own_deadlines(self) -> None:
        """A pre-P4 row (the v1 copy and v1 deadlines) reads; its deadlines are v1's arithmetic, not the current's."""
        record = with_policy(run_with_long(), LONG_POLICY_V1)
        row = record['clips']['L']['output']
        row['preparationElapsed'] = V1_PREPARATION_600
        schema.validate_record(stored(record))
        self.assertEqual(known_long_policy(stored(record)['clips']['L']['output']['policy']), 'v1')
        self.assertEqual(formats.expected_deadlines('long', 0.0, 600.0, row['policy']), (6905.0, 10800.0))
        # Rounded to the millisecond, as recorded: 10800 - 1854.3 - (2.9 x 834.3 + 80) x 1.25 = 5821.3625.
        self.assertEqual(formats.expected_deadlines('long', 0.0, 834.3, LONG_POLICY_V1), (5821.363, 10800.0))
        self.assertEqual(formats.clip_deadlines(record, record['clips']['L']),
                         {'preparationSeconds': 6905.0, 'draftDecisionSeconds': 6905.0, 'deliverySeconds': 10800.0,
                          'handoffReserveSeconds': 1620.0, 'cleanupReserveSeconds': 45})
        self.assertEqual(formats.clip_limits(record, record['clips']['L']), LONG_POLICY_V1['limits'])
        self.assertIs(formats.clip_rates(record, record['clips']['L']), row['policy']['rates'])

    def test_v2_row_with_each_late_mode_reads(self) -> None:
        """v2 with refuse, or labeled with an int grace in (0, 10800], reads; the late mode moves no deadline."""
        for late in ({'mode': 'refuse'}, {'mode': 'labeled', 'graceSeconds': 3600},
                     {'mode': 'labeled', 'graceSeconds': 1}, {'mode': 'labeled', 'graceSeconds': 10800}):
            with self.subTest(late=late):
                record = stored(with_policy(run_with_long(), v2_with(late)))
                schema.validate_record(record)
                self.assertEqual(known_long_policy(record['clips']['L']['output']['policy']), 'v2')

    def test_forged_or_unknown_policy_is_refused_by_name(self) -> None:
        """A changed number, an unknown or missing key, a bad late mode or a JSON type swap is refused by name."""
        final = copy.deepcopy(LONG_POLICY_V1)
        final['rates']['routes']['final']['perOutputSecond'] = 2.8
        forged = [final, {**LONG_POLICY_V1, 'lateDelivery': {'mode': 'refuse'}}, {**LONG_POLICY_V1, 'version': 1},
                  {**LONG_POLICY_V1, 'deliverySeconds': 10800.0}, {**LONG_POLICY_V1, 'maxOutputSeconds': 901},
                  {**LONG_POLICY_V1, 'limits': {**LONG_POLICY_V1['limits'], 'transientRetry': True}},
                  copy.deepcopy(LONG_POLICY_V2), {**v2_with({'mode': 'refuse'}), 'extra': 1},
                  {key: value for key, value in CURRENT_LONG_POLICY.items() if key != 'limits'}, None, 'v1', []]
        for grace in (0, 10801, 3600.0, True, None, -1):
            forged.append(v2_with({'mode': 'labeled', 'graceSeconds': grace}))
        forged += [v2_with({'mode': 'labeled'}), v2_with({'mode': 'refuse', 'graceSeconds': 3600}),
                   v2_with({'mode': 'late', 'graceSeconds': 3600}), v2_with({'mode': 'Refuse'}), v2_with(None)]
        for policy in forged:
            with self.subTest(policy=policy if type(policy) is not dict else sorted(policy)):
                self.assert_unknown(policy)

    def assert_unknown(self, policy: object) -> None:
        """``policy`` is no known version, and a record whose Long row carries it is refused by name on read."""
        self.assertIsNone(known_long_policy(policy))
        with self.assertRaisesRegex(ValueError, UNKNOWN):
            schema.validate_record(stored(with_policy(run_with_long(), policy)))

    def test_new_authorization_freezes_current_policy(self) -> None:
        """``authorize_output`` writes a copy of the current policy (v2 with its late mode) through the alias."""
        record = run_with_long()
        row = record['clips']['L']['output']
        schema.validate_record(stored(record))
        self.assertEqual(known_long_policy(stored(record)['clips']['L']['output']['policy']), 'v2')
        self.assertEqual(json.dumps(row['policy'], sort_keys=True), json.dumps(CURRENT_LONG_POLICY, sort_keys=True))
        self.assertIsNot(row['policy'], CURRENT_LONG_POLICY)
        self.assertIs(formats.LONG_POLICY, CURRENT_LONG_POLICY)
        self.assertEqual((known_long_policy(row['policy']), row['policy']['version'], row['policy']['lateDelivery']),
                         ('v2', 2, long_policy.LATE_LONG_DELIVERY))
        self.assertEqual((row['preparationElapsed'], row['deadlineElapsed']),
                         formats.expected_deadlines('long', 0.0, 600.0, CURRENT_LONG_POLICY))

    def test_short_records_unchanged(self) -> None:
        """A Shorts-only record and an own-clock Short validate as before; a Short's deadlines take no Long policy."""
        with fake_clock(FakeClock()):
            spec = BatchSpec('batch-shorts', ('A', 'B'), (), 1, approvals={clip: approval(clip) for clip in ('A', 'B')})
            record = new_batch_record(spec, start_anchor())
        schema.validate_record(record)
        self.assertEqual(formats.clip_deadlines(record, record['clips']['A']), record['deadlines'])
        with mock.patch('studio.production.outputs.admission_refusal', return_value=None):
            row = authorize_output(record, OutputAuthorization('N', 'short', 'TEST Short N', 'TEST operator',
                                                               approval=approval('N')), 1800.0)['output']
        schema.validate_record(record)
        self.assertEqual((row['policy'], row['preparationElapsed'], row['deadlineElapsed']), (None, 3300.0, 4200.0))
        self.assertEqual(formats.expected_deadlines('short', 1800.0, None, None), (3300.0, 4200.0))

    def test_reserves_deadlines_limits_and_rates_come_from_the_rows_own_copy(self) -> None:
        """Every per-output read uses the row's copy: a TEST copy whose reserves differ from every known version
        moves the hand-off reserve, cleanup reserve, deadlines, limits and rates it yields (read, never validated)."""
        own = copy.deepcopy(LONG_POLICY_V1)
        own.update(deliverySeconds=7200, cleanupReserveSeconds=10, limits={**own['limits'], 'author': 1})
        own['handoffReserve'] = {**own['handoffReserve'], 'reviewNotesSeconds': 0}
        own['rates']['routes']['final'] = {'perOutputSecond': 2.0, 'fixedSeconds': 80.0}   # (2 x 600 + 80) x 1.25
        record = with_policy(run_with_long(), own)
        clip = record['clips']['L']
        deadlines = formats.clip_deadlines(record, clip)
        self.assertEqual((deadlines['handoffReserveSeconds'], deadlines['cleanupReserveSeconds']), (1020.0, 10))
        self.assertEqual(formats.long_handoff_seconds(600.0, own), 1020.0)
        self.assertEqual(formats.expected_deadlines('long', 0.0, 600.0, own), (7200.0 - 1020.0 - 1600.0, 7200.0))
        self.assertEqual(formats.clip_limits(record, clip)['author'], 1)
        self.assertIs(formats.clip_rates(record, clip), clip['output']['policy']['rates'])

    def test_v1_is_the_pre_p4_policy_byte_for_byte(self) -> None:
        """The v1 copy equals the pre-P4 ``formats.LONG_POLICY`` in every value and JSON type."""
        text = json.dumps(LONG_POLICY_V1, sort_keys=True, separators=(',', ':'))
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), V1_CANONICAL_SHA256)
        self.assertEqual(known_long_policy(LONG_POLICY_V1), 'v1')

    def test_the_policy_catalog_never_imports_formats(self) -> None:
        """``long_policy`` imports no engine module, so ``formats`` can import it without a cycle."""
        tree = ast.parse(Path(long_policy.__file__).read_text(encoding='utf-8'))
        imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertEqual(sorted(imported), ['__future__', 'json'])


if __name__ == '__main__':
    unittest.main()
