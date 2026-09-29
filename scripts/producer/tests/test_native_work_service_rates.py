"""Rate-only private IO and cold validation; synthetic fixtures never qualify a host."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_service_rate_fixture import HOST, fixture, saved
from native_work_service_pins import MAX_DOCUMENT_BYTES, ServiceRateError, document, parse
from native_work_service_evidence import validate_coverage, validate_failures
from native_work_service_runs import validate_run, validate_timing
from native_work_service_rates import RECORD_NAME, read_service_rates, write_service_rates
from native_work_service_schema import validate_document


class ServiceRateTests(unittest.TestCase):
    """Exercise real cold readers and private durable files without live host writes."""

    def setUp(self) -> None:
        """Create isolated TEST media/proofs and substitute only host-runtime bindings."""
        self.temp = tempfile.TemporaryDirectory(prefix='TEST-service-rates-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.record, bindings = fixture(self.root)
        self.provenance = {key: self.record['serviceRates'][0][key] for key in ('engine', 'tools', 'harness')}
        self.directory = self.root / 'private' / 'native-pool'
        self.enterContext(patch('native_work_service_rates.record_directory', return_value=self.directory))
        self.enterContext(patch('native_work_service_schema.current_bindings', return_value=bindings))

    def test_exact_roundtrip_never_writes_capacity_records(self) -> None:
        """Actual sidecar IO validates original owner and media pins, separate from capacity."""
        self.assertEqual(read_service_rates(HOST).rows, ())
        result = write_service_rates(self.record, HOST)
        catalog = read_service_rates(HOST)
        self.assertEqual(catalog.rows, tuple(self.record['serviceRates']))
        self.assertEqual(catalog.source, result)
        self.assertIsNone(catalog.rejected)
        self.assertEqual([path.name for path in self.directory.iterdir()], [RECORD_NAME])

    def test_changed_current_media_returns_fallback(self) -> None:
        """Changed held-out media invalidates even an otherwise immutable adopted sidecar."""
        write_service_rates(self.record, HOST)
        (self.root / 'held.bin').write_bytes(b'changed held-out bytes')
        catalog = read_service_rates(HOST)
        self.assertEqual(catalog.rows, ())
        self.assertIn('changed', catalog.rejected)

    def test_noncanonical_namespace_never_reads_or_writes(self) -> None:
        """Private test namespaces do not inherit live-host evidence or create new authority."""
        with patch('native_work_service_rates.record_directory', return_value=None):
            self.assertEqual(read_service_rates(HOST).rows, ())
            with self.assertRaisesRegex(ServiceRateError, 'canonical'):
                write_service_rates(self.record, HOST)
        self.assertFalse(self.directory.exists())

    def test_strict_shape_format_host_and_measured_arithmetic(self) -> None:
        """No stale host, invented maximum, optimistic ceiling, warm default or wrong audio."""
        changes = [lambda row: row.update(schemaVersion=True),
                   lambda row: row.update(capacity={'heavy': 3}),
                   lambda row: row['host'].update(other='host'),
                   lambda row: row['serviceRates'][0]['cells'][0].update(ceilingSeconds=1.),
                   lambda row: row['serviceRates'][0]['cells'][0]['bounds'].update(maxPictureBytes=101),
                   lambda row: row['serviceRates'][0]['cells'][0]['contract'].update(cacheRegime='observed-warm'),
                   lambda row: row['serviceRates'][0]['cells'][0]['contract']['audio'].update(channels=True),
                   lambda row: row['serviceRates'][0]['cells'][0]['contract']['canvas'].update(frameRate='25')]
        for change in changes:
            candidate = copy.deepcopy(self.record)
            change(candidate)
            with self.subTest(change=change), self.assertRaises((ValueError, RuntimeError)):
                validate_document(candidate, HOST)

    def test_independent_adoption_and_heldout_binding_are_required(self) -> None:
        """Neither passed flags nor changed validation metadata transfer adoption."""
        row = self.record['serviceRates'][0]
        validation = json.loads(Path(row['adoption']['validation']['path']).read_text())
        validation['heldOutRunIds'] = []
        row['adoption']['validation'] = saved(self.root, 'changed-validation.json', validation)
        with self.assertRaisesRegex(ValueError, 'held-out'):
            validate_document(self.record, HOST)

    def test_json_bound_precedes_hashing_and_duplicate_keys_are_refused(self) -> None:
        """Oversized JSON never triggers an unbounded hash; ambiguous JSON is not accepted."""
        value = {'path': str(self.root / 'missing'), 'bytes': MAX_DOCUMENT_BYTES + 1, 'sha256': 'a' * 64}
        with patch('native_work_service_pins.file_hash') as hashing:
            with self.assertRaisesRegex(ValueError, 'size bound'):
                document(value)
            hashing.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            parse(b'{"x":1,"x":2}')

    def test_symlink_evidence_and_corrupt_record_return_fallback(self) -> None:
        """No-follow evidence and the canonical durable record reject replacement links."""
        write_service_rates(self.record, HOST)
        file = self.directory / RECORD_NAME
        file.write_text('{"schemaVersion":1,"schemaVersion":1}')
        self.assertEqual(read_service_rates(HOST).rows, ())
        link = self.root / 'linked'
        link.symlink_to(self.root / 'held.bin')
        value = saved(self.root, 'small.json', {'test': True})
        value['path'] = str(link)
        with self.assertRaises((ValueError, RuntimeError)):
            document(value)

    def test_parent_timing_cannot_remove_cleanup_or_invent_queue_wait(self) -> None:
        """Measured service is outer elapsed minus the actual owner's queue interval only."""
        manifest = document(self.record['serviceRates'][0]['measurement']['manifest'])
        run = validate_run(manifest['runs'][0], self.provenance)
        owner = json.loads(Path(run['inspection']['owner']).read_text())
        timing = dict(run['timing'], queueSeconds=2., serviceSeconds=9.)
        with self.assertRaisesRegex(ValueError, 'Queue deduction'):
            validate_timing(timing, owner)
        timing = dict(run['timing'], finishedEpoch=run['timing']['startedEpoch'] + 5,
                      grossSeconds=5., serviceSeconds=4.)
        with self.assertRaisesRegex(ValueError, 'omits owner'):
            validate_timing(timing, owner)

    def test_joint_bounds_and_heldout_latency_must_be_exercised(self) -> None:
        """Independent maxima cannot invent a combination and slow held-out cases cannot vanish."""
        row = self.record['serviceRates'][0]
        manifest = document(row['measurement']['manifest'])
        runs = {item['id']: validate_run(item, self.provenance) for item in manifest['runs']}
        cell = copy.deepcopy(row['cells'][0])
        cell['bounds']['maxMasterBytes'] += 1
        with self.assertRaisesRegex(ValueError, 'jointly'):
            validate_coverage(cell, runs)
        runs['held']['timing']['serviceSeconds'] = 13.
        with self.assertRaisesRegex(ValueError, 'Held-out service'):
            validate_coverage(row['cells'][0], runs)

    def test_omitted_work_and_failure_without_retained_evidence_refuse(self) -> None:
        """No zero-cost omitted operation or disappeared failed attempt is admitted."""
        manifest = document(self.record['serviceRates'][0]['measurement']['manifest'])
        entry = manifest['runs'][0]
        value = document(entry['measurement'])
        value['unsupportedOperations'] = ['TEST-unmeasured-current-reader']
        entry['measurement'] = saved(self.root, 'unsupported.json', value)
        with self.assertRaisesRegex(ValueError, 'Unmeasured operations'):
            validate_run(entry, self.provenance)
        with self.assertRaisesRegex(ValueError, 'no retained'):
            validate_failures([{'id': 'failed', 'owner': None, 'diagnostic': None}], {})
        diagnostic = saved(self.root, 'failure.log', b'TEST retained failure')
        self.assertEqual(validate_failures([{'id': 'failed', 'owner': None, 'diagnostic': diagnostic}], {}), ['failed'])


if __name__ == '__main__':
    unittest.main()
