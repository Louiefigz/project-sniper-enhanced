"""Direct telemetry parsing and shared process authority without OS or media work."""
from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from native_render_macos import COMPRESSED_UNAVAILABLE, SAMPLER
from native_render_measurements import DirectMeasurementError, parse_direct
from native_render_processes import MissingProcessFootprint, ProcessIdentity, ProcessRequest
from native_render_resources import GIB, ResourceMeasurementError, parse_snapshot, read_snapshot
from test_native_render_resources import IDENTITY, REQUEST, START, direct_sample, raw_sample


def payload() -> dict:
    """Reuse the synthetic complete direct schema used by historical-row regressions."""
    return json.loads(direct_sample()['direct'])


def parse(value: object, ps: str | None = None, request: ProcessRequest = REQUEST) -> dict:
    """Exercise public deserialization and real ownership selection together."""
    return parse_direct(json.dumps(value), ps if ps is not None else direct_sample()['ps'], request)


class NativeRenderMeasurementTests(unittest.TestCase):
    """Reject uncertainty without relabeling denied live processes as exited."""

    def test_physical_footprint_and_null_compression_keep_source_provenance(self) -> None:
        """Physical footprint is already inclusive; null CMPRS is not zero or RSS."""
        value = payload()
        value['processes'][0]['footprintBytes'] = 214041128
        value['processes'][0]['residentBytes'] = 4096
        result = parse(value)
        owned = result['selection']['processes']
        self.assertEqual([row.pid for row in owned], [100, 101])
        self.assertEqual(owned[0].footprint_bytes, 214041128)
        self.assertTrue(all(row.compressed_bytes is None for row in owned))
        self.assertTrue(all(row.memory_sampler == SAMPLER for row in owned))
        self.assertTrue(all(row.compressed_status == COMPRESSED_UNAVAILABLE for row in owned))
        self.assertTrue(all(row.process_start_abstime_before == row.process_start_abstime
                            and row.process_exit_abstime == 0 for row in owned))
        self.assertEqual(result['compressor'], 2 * GIB)
        self.assertEqual(result['unused'], 34 * GIB)

    def test_wrong_missing_or_unknown_top_level_state_retains_rejected_evidence(self) -> None:
        """Only an explicit successful direct sample may enter resource policy."""
        for status in (None, 'unavailable', 'ok', '', True, [], {}):
            value = payload() | {'status': status}
            with self.subTest(status=status), self.assertRaises(DirectMeasurementError) as caught:
                parse(value)
            self.assertEqual(caught.exception.evidence['payload'], value)
            self.assertEqual(caught.exception.evidence['sampler'], SAMPLER)
        value = payload()
        del value['status']
        with self.assertRaises(DirectMeasurementError):
            parse(value)

    def test_unknown_schema_or_sampler_cannot_be_reinterpreted(self) -> None:
        """No schema coercion or implicit historical-top fallback is permitted."""
        for key, values in [('schemaVersion', [True, 1.0, '1', 0, 2, None]),
                            ('sampler', ['macos-top-v1', 'rss', '', None])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(DirectMeasurementError):
                    parse(payload() | {key: value})

    def test_required_top_level_fields_and_object_shapes_are_checked(self) -> None:
        """A partial payload cannot acquire healthy defaults."""
        for key in ('schemaVersion', 'sampler', 'elapsedSeconds', 'host', 'processes'):
            value = payload()
            del value[key]
            with self.subTest(missing=key), self.assertRaises(DirectMeasurementError):
                parse(value)
        for value in (None, [], 'measured', 1):
            with self.subTest(shape=value), self.assertRaises(DirectMeasurementError):
                parse(value)

    def test_sample_duration_must_be_finite_nonnegative_number(self) -> None:
        """JSON NaN and booleans cannot pass numeric duration validation."""
        for elapsed in (True, -1, float('nan'), float('inf'), -float('inf'), None, '.1'):
            with self.subTest(elapsed=elapsed), self.assertRaises(DirectMeasurementError):
                parse(payload() | {'elapsedSeconds': elapsed})

    def test_process_counters_reject_bool_fraction_negative_nonfinite_and_overflow(self) -> None:
        """Each public integer field must remain an unsigned integer after JSON parsing."""
        fields = ('pid', 'footprintBytes', 'processStartAbstime', 'processStartAbstimeBefore', 'processExitAbstime')
        invalid = (True, 1.5, -1, float('nan'), float('inf'), None, '100', 2**64)
        for field in fields:
            for counter in invalid:
                value = payload()
                value['processes'][0][field] = counter
                with self.subTest(field=field, counter=counter), self.assertRaises(DirectMeasurementError):
                    parse(value)

    def test_host_counters_reject_invalid_unsigned_values(self) -> None:
        """Both declared byte totals and the independent page counters are validated."""
        fields = ('pageSizeBytes', 'returnedIntegerCount', 'compressorBytes', 'unusedPhysicalBytes',
                  'compressor_page_count', 'free_count', 'speculative_count')
        for field in fields:
            for counter in (True, 1.5, -1, float('nan'), float('inf'), None, '2', 2**64):
                value = payload()
                target = value['host']['raw'] if field.endswith('count') else value['host']
                target[field] = counter
                with self.subTest(field=field, counter=counter), self.assertRaises(DirectMeasurementError):
                    parse(value)

    def test_missing_process_counter_and_compressed_provenance_are_not_defaulted(self) -> None:
        """All successful process readings need their complete identity and metric labels."""
        for field in payload()['processes'][0]:
            value = payload()
            del value['processes'][0][field]
            with self.subTest(missing=field), self.assertRaises(DirectMeasurementError):
                parse(value)

    def test_direct_compression_cannot_claim_zero_or_a_measured_value(self) -> None:
        """Unavailable compression must remain explicit instead of borrowing top's meaning."""
        changes = [('compressedBytes', 0), ('compressedBytes', 4096),
                   ('compressedStatus', 'measured'), ('compressedStatus', None),
                   ('footprintSource', 'proc_pid_rusage:RUSAGE_INFO_V0:ri_resident_size')]
        for key, value in changes:
            record = payload()
            record['processes'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(DirectMeasurementError):
                parse(record)

    def test_paired_start_changes_zero_start_and_exited_measured_rows_fail(self) -> None:
        """A claimed measurement is invalid if its kernel task was replaced or exited."""
        changes = [('processStartAbstime', 999), ('processStartAbstime', 0),
                   ('processStartAbstimeBefore', 0), ('processExitAbstime', 1)]
        for key, value in changes:
            record = payload()
            record['processes'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(DirectMeasurementError):
                parse(record)

    def test_host_formula_uses_inclusive_free_and_physical_compressor_pages(self) -> None:
        """Speculative pages are not added again and logical compression is not physical."""
        for key in ('unusedPhysicalBytes', 'compressorBytes'):
            value = payload()
            value['host'][key] += value['host']['raw']['speculative_count'] * value['host']['pageSizeBytes']
            with self.subTest(formula=key), self.assertRaisesRegex(DirectMeasurementError, 'formula mismatch'):
                parse(value)
        value = payload()
        value['host']['raw']['speculative_count'] = value['host']['raw']['free_count'] + 1
        with self.assertRaisesRegex(DirectMeasurementError, 'Speculative'):
            parse(value)

    def test_host_count_page_size_and_symbol_provenance_must_match(self) -> None:
        """The ABI-backed counters cannot use a short buffer or user-page-size label."""
        for key, values in [('pageSizeBytes', [0, 8192, 65536]),
                            ('returnedIntegerCount', [37, 39]), ('pageSizeSource', ['host_page_size', None])]:
            for value in values:
                record = payload()
                record['host'][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(DirectMeasurementError):
                    parse(record)

    def test_host_totals_cannot_exceed_separately_measured_physical_capacity(self) -> None:
        """Internally matching page formulas do not make impossible host totals valid."""
        for field, pages in [('unusedPhysicalBytes', 'free_count'), ('compressorBytes', 'compressor_page_count')]:
            record, raw = payload(), direct_sample()
            record['host'][field] = 65 * GIB
            record['host']['raw'][pages] = 65 * GIB // record['host']['pageSizeBytes']
            raw['direct'] = json.dumps(record)
            with self.subTest(field=field), self.assertRaisesRegex(ResourceMeasurementError, 'physical capacity'):
                parse_snapshot(raw, REQUEST, 40 * GIB)

    def test_disjoint_host_categories_cannot_sum_above_physical_capacity(self) -> None:
        """Individually plausible counters still cannot occupy more RAM than exists."""
        record, raw = payload(), direct_sample()
        record['host']['compressorBytes'] = 40 * GIB
        record['host']['raw']['compressor_page_count'] = 40 * GIB // record['host']['pageSizeBytes']
        raw['direct'] = json.dumps(record)
        with self.assertRaisesRegex(ResourceMeasurementError, 'physical capacity'):
            parse_snapshot(raw, REQUEST, 40 * GIB)

    def test_process_rows_are_bounded_unique_and_structurally_valid(self) -> None:
        """Malformed or duplicate rows cannot hide live owned memory by overwriting it."""
        one = payload()['processes'][0]
        cases = [None, {}, [one, deepcopy(one)], [None], [one | {'status': None}],
                 [one | {'status': 'exited'}], [one | {'pid': 1}],
                 [{'pid': pid, 'status': 'unavailable'} for pid in range(2, 4099)]]
        for rows in cases:
            with self.subTest(count=len(rows) if isinstance(rows, list) else None), self.assertRaises(DirectMeasurementError):
                parse(payload() | {'processes': rows})

    def test_missing_or_disappeared_live_child_is_retryable_with_exact_failed_evidence(self) -> None:
        """A live child in ps must be measured even if libproc says ESRCH."""
        for replacement in (None, {'pid': 101, 'status': 'unavailable', 'result': -1, 'errno': 3}):
            value = payload()
            value['processes'] = [row for row in value['processes'] if row['pid'] != 101]
            if replacement:
                value['processes'].append(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(MissingProcessFootprint) as caught:
                parse(value)
            self.assertEqual(caught.exception.identities, (ProcessIdentity(101, START, 101),))
            self.assertEqual(caught.exception.evidence['directReadings'], value)
            self.assertEqual(caught.exception.evidence['sampler'], SAMPLER)

    def test_permission_unknown_and_unexplained_unavailable_rows_are_terminal(self) -> None:
        """Only explicit ESRCH can request a retry; denial must preserve fail-fast semantics."""
        cases = [{'pid': 101, 'status': 'unavailable', 'result': -1, 'errno': code}
                 for code in (1, 13, 0, 95, 999, None, True, 3.0)]
        cases.append({'pid': 101, 'status': 'unavailable'})
        for row in cases:
            value = payload()
            value['processes'][1] = row
            with self.subTest(row=row), self.assertRaises(DirectMeasurementError) as caught:
                parse(value)
            self.assertEqual(caught.exception.evidence['payload'], value)

    def test_exited_registered_root_and_live_detached_child_use_shared_selection(self) -> None:
        """An absent root is exited; a pinned live orphan still contributes footprint."""
        request = ProcessRequest(IDENTITY, (ProcessIdentity(101, START, 101),))
        ps = f'101 1 101 {START}\n500 1 500 {START}\n'
        value = payload()
        value['processes'][0] = {'pid': 100, 'status': 'unavailable', 'result': -1, 'errno': 3}
        selected = parse(value, ps, request)['selection']
        self.assertEqual(selected['missing'], (100,))
        self.assertEqual([row.pid for row in selected['processes']], [101])
        self.assertEqual(selected['processes'][0].footprint_bytes, GIB)
        self.assertTrue(selected['verified'])

    def test_reused_registered_pid_is_excluded_instead_of_becoming_owned(self) -> None:
        """A matching number with another lstart is unrelated despite a valid API row."""
        request = ProcessRequest(None, (ProcessIdentity(101, START, 101),))
        ps = f'101 1 101 a different start\n500 1 500 {START}\n'
        selected = parse(payload(), ps, request)['selection']
        self.assertEqual(selected['reused'], (101,))
        self.assertEqual(selected['processes'], ())
        self.assertFalse(selected['verified'])

    def test_no_owned_processes_needs_no_footprint_but_still_requires_host(self) -> None:
        """An intentionally empty discovery set differs from a missing live owned row."""
        result = parse(payload() | {'processes': []}, request=ProcessRequest())
        self.assertEqual(result['selection']['processes'], ())
        with self.assertRaises(MissingProcessFootprint):
            parse(payload() | {'processes': []})

    def test_malformed_or_oversized_json_keeps_typed_failure(self) -> None:
        """An invalid subprocess response must not become an untyped or healthy result."""
        for text in ('{broken', ' ' * (8 * 1024 * 1024 + 1)):
            with self.subTest(length=len(text)), self.assertRaises(DirectMeasurementError):
                parse_direct(text, direct_sample()['ps'], REQUEST)

    def test_mixed_sampler_payloads_cannot_choose_the_healthier_reading(self) -> None:
        """Historical top remains supported but cannot accompany a direct reading."""
        raw = direct_sample() | {'top': raw_sample()['top']}
        with self.assertRaisesRegex(ResourceMeasurementError, 'Exactly one'):
            parse_snapshot(raw, REQUEST, 40 * GIB)
        historic = parse_snapshot(raw_sample(), REQUEST, 40 * GIB)
        self.assertEqual(historic.memory_sampler, 'macos-top-v1')
        self.assertEqual([row.compressed_bytes for row in historic.processes], [GIB, GIB // 2])

    def test_read_snapshot_keeps_missing_and_invalid_live_readings_as_failures(self) -> None:
        """The complete owner path cannot turn API failure into process exit."""
        changes = [{'pid': 101, 'status': 'unavailable', 'result': -1, 'errno': 3},
                   payload()['processes'][1] | {'processStartAbstimeBefore': 9},
                   payload()['processes'][1] | {'processExitAbstime': 1}]
        for changed in changes:
            raw, record = direct_sample(), payload()
            record['processes'][1] = changed
            commands = [raw['sysctl'], raw['pressure'], raw['ps'], json.dumps(record), raw['ps']]
            error = MissingProcessFootprint if changed['status'] == 'unavailable' else DirectMeasurementError
            with self.subTest(changed=changed), \
                    patch('native_render_resources._read_command', side_effect=commands) as read, \
                    patch('native_render_resources.shutil.disk_usage', return_value=SimpleNamespace(free=40 * GIB)):
                with self.assertRaises(error):
                    read_snapshot(Path('/mock-project'), REQUEST)
                self.assertEqual(read.call_count, 5)

    def test_read_snapshot_reconciles_exited_and_recycled_children(self) -> None:
        """The second ps read, not an unavailable API row, establishes disappearance."""
        raw, record = direct_sample(), payload()
        record['processes'][1] = {'pid': 101, 'status': 'unavailable', 'result': -1, 'errno': 3}
        for child in ('', '101 1 101 a different start\n'):
            after = f'100 1 100 {START}\n500 1 500 {START}\n' + child
            commands = [raw['sysctl'], raw['pressure'], raw['ps'], json.dumps(record), after]
            with self.subTest(child=child), patch('native_render_resources._read_command', side_effect=commands), \
                    patch('native_render_resources.shutil.disk_usage', return_value=SimpleNamespace(free=40 * GIB)):
                snapshot = read_snapshot(Path('/mock-project'), REQUEST)
            self.assertEqual(snapshot.owned_pids, (100,))
            self.assertEqual(snapshot.reused_registered_pids if child else snapshot.missing_registered_pids, (101,))


if __name__ == '__main__':
    unittest.main()
