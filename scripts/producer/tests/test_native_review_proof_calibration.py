"""Cold-reader proof-owner fixtures are synthetic, never actual measured evidence."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_service_rate_fixture import fixture, owned, saved
from cut_preview_io import bound_json, digest
from native_proof_io import COLLECTOR
from native_review_proof_calibration import (
    PLAN_KIND, RESULT_KIND, UNSUPPORTED, proof_read, read_proof_inspection, validate_plan,
)
from studio.owned_inspection import STATUS


class ProofCalibrationTests(unittest.TestCase):
    """Use actual inspection/provenance/counter readers around marked TEST receipts."""

    def setUp(self) -> None:
        """Retain a closed synthetic preparation and exact repeated read request."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        record, _bindings = fixture(self.root)
        row = record['serviceRates'][0]
        self.provenance = {key: row[key] for key in ('engine', 'tools', 'harness')}
        self.input = saved(self.root, 'technical-proof.bin', b'TEST owned proof bytes')
        prepared = {'kind': 'native-long-review-package-technical-preparation',
                    'productionAuthority': False, 'outputPins': [self.input]}
        self.preparation = owned(self.root, 'prepare-proof', prepared,
                                 (self.provenance, None, None, None))
        self.plan = {'schemaVersion': 1, 'kind': PLAN_KIND, 'collector': COLLECTOR,
                     'reads': [self.input, self.input]}
        self.request = {'preparation': self.preparation, 'proofPlan': self.plan, 'measurementId': 'TEST-proof'}
        self.raw = self.observation()
        with patch('native_review_proof_calibration.measure_read_pass', return_value=self.raw):
            self.result = proof_read(self.request)
        self.reference = self.publish(self.result, self.request)

    def observation(self) -> dict:
        """Explicitly synthetic raw pass shares a captured TEST worker identity."""
        identity = {'pid': 100, 'pgid': 100, 'started': 'TEST-only'}
        bsd = {'status': 'measured', 'parentPid': 99, 'identity': identity}
        before = {'status': 'measured', 'pid': 100, 'processStart': 1, 'processExit': 0,
                  'absoluteTime': 10, 'diskReadBytes': 100, 'diskWriteBytes': 0}
        return {'schemaVersion': 1, 'collector': COLLECTOR, 'pid': 100,
                'clock': 'monotonic-nanoseconds', 'kernelStartClock': 'mach-absolute-ticks',
                'method': 'proc_pid_rusage-v2', 'status': 'measured', 'reason': None,
                'logicalReads': [{'input': row, 'returnedBytes': row['bytes']} for row in self.plan['reads']],
                'before': before, 'after': before | {'absoluteTime': 20, 'diskReadBytes': 112},
                'topologyBefore': {'accepted': True}, 'topologyAfter': {'accepted': True},
                'identityBefore': bsd, 'identityAfter': copy.deepcopy(bsd)}

    def publish(self, result: dict, additions: dict) -> dict:
        """Create TEST owner-bound bytes, using real cold reader field requirements."""
        reference = owned(self.root, 'proof-owner', result,
                          (self.provenance, self.preparation, None, None))
        file = Path(reference['path']).with_name('request.json')
        request = bound_json(file) | additions | {'operation': 'proof-read'}
        request_pin = saved(file.parent, file.name, request)
        owner_file = Path(reference['owner'])
        owner = bound_json(owner_file)
        owner['additionalFilePinsBefore'][str(file)] = request_pin['sha256']
        owner['additionalFilePinsAfter'][str(file)] = request_pin['sha256']
        reference['ownerSha256'] = saved(owner_file.parent, owner_file.name, owner)['sha256']
        return reference

    def checked(self) -> dict:
        """Exercise full captured-output, current-provenance and raw-pass readers."""
        return read_proof_inspection(self.reference, self.provenance)

    def test_repeated_plan_and_exact_owner_identity_bound_to_raw_pass(self) -> None:
        """Only actual ordered bytes and task interval deltas enter returned totals."""
        checked = self.checked()
        self.assertEqual(checked['logicalReadBytes'], 2 * self.input['bytes'])
        self.assertEqual(checked['taskDiskReadBytes'], 12)
        self.assertEqual(checked['result']['unsupportedOperations'], UNSUPPORTED)
        self.assertEqual(checked['result']['kind'], RESULT_KIND)
        self.assertFalse(checked['result']['productionAuthority'])

    def test_repinning_changed_raw_result_cannot_replace_owner_output(self) -> None:
        """Outer reference edits cannot rewrite original captured worker bytes."""
        file = Path(self.reference['path'])
        changed = copy.deepcopy(self.result)
        changed['rawObservation']['after']['diskReadBytes'] += 1000
        self.reference['sha256'] = saved(file.parent, file.name, changed)['sha256']
        with self.assertRaisesRegex(ValueError, 'owner-captured result differs'):
            self.checked()

    def test_owner_cannot_relabel_run_plan_or_preparation(self) -> None:
        """Even newly constructed TEST owners must agree with their result's request."""
        variants = [{'measurementId': 'other'}, {'proofPlan': self.plan | {'reads': [self.input]}},
                    {'preparation': {'path': 'other'}}]
        for changed in variants:
            self.reference = self.publish(self.result, self.request | changed)
            self.assert_refused('original owner request')

    def assert_refused(self, message: str) -> None:
        """Check a concrete cold-reader boundary independently of outer test loops."""
        with self.assertRaisesRegex(ValueError, message):
            self.checked()

    def test_parent_identity_and_missing_process_coverage_refuse(self) -> None:
        """Same PID with another captured start, group or parent is not this worker."""
        for changes in ({'started': 'other'}, {'pgid': 300}, {'parent_pid': 300}):
            self.reference = self.publish(self.result, self.request)
            file = Path(self.reference['owner'])
            owner = bound_json(file)
            owner['ownerIdentities'][0].update(changes)
            self.reference['ownerSha256'] = saved(file.parent, file.name, owner)['sha256']
            self.assert_refused('kernel proof|parent differs|root owner identity is incomplete')
        self.reference = self.publish(self.result, self.request)
        file = Path(self.reference['owner'])
        owner = bound_json(file)
        owner['ownerIdentities'].append({'pid': 101, 'pgid': 100, 'parent_pid': 100, 'started': 'TEST-child'})
        self.reference['ownerSha256'] = saved(file.parent, file.name, owner)['sha256']
        self.assert_refused('one exact process')

    def test_missing_or_reordered_reads_cannot_claim_complete_plan(self) -> None:
        """Counter evidence covers the actual requested multiplicity, not unique pins."""
        result = copy.deepcopy(self.result)
        result['rawObservation']['logicalReads'].pop()
        self.reference = self.publish(result, self.request)
        self.assert_refused('plan is incomplete')
        result['rawObservation']['logicalReads'] = [{'input': self.input, 'returnedBytes': 1}] * 2
        self.reference = self.publish(result, self.request)
        self.assert_refused('ordered plan')

    def test_unavailable_counters_and_read_failures_are_distinct(self) -> None:
        """Unavailable physical observations stay null; failed input integrity refuses."""
        result = copy.deepcopy(self.result)
        result['rawObservation'].update(status='unavailable', reason='kernel-counter-unavailable')
        self.reference = self.publish(result, self.request)
        self.assertIsNone(self.checked()['taskDiskReadBytes'])
        self.assertEqual(self.checked()['logicalReadBytes'], 2 * self.input['bytes'])
        result['rawObservation'].update(status='failed', reason='input-read-failed')
        self.reference = self.publish(result, self.request)
        self.assert_refused('Proof read failed')

    def test_only_prepared_bounded_inputs_and_current_bytes_allowed(self) -> None:
        """The pass cannot expand its source closure or silently retain changed bytes."""
        outside = saved(self.root, 'outside.bin', b'not prepared')
        prepared = {'kind': 'native-long-review-package-technical-preparation',
                    'productionAuthority': False, 'outputPins': [self.input]}
        with self.assertRaisesRegex(ValueError, 'escaped prepared'):
            validate_plan(self.plan | {'reads': [outside]}, prepared)
        Path(self.input['path']).write_bytes(b'changed')
        self.assert_refused('input changed')

    def test_worker_dispatch_uses_existing_gates_before_and_after(self) -> None:
        """Only operation dispatch is substituted; existing live checks remain in order."""
        from native_review_calibration_worker import execute
        request = self.request | {'operation': 'proof-read'}
        with patch('native_review_calibration_worker.require_worker', return_value=request), \
                patch('native_review_calibration_worker.require_session') as session, \
                patch('native_review_calibration_worker.require_provenance') as provenance, \
                patch('native_review_calibration_worker.proof_read', return_value=self.result) as measure:
            execute(self.root / 'request.json')
        measure.assert_called_once_with(request)
        self.assertEqual(session.call_count, 2)
        self.assertEqual(provenance.call_count, 2)
        self.assertEqual(bound_json(self.root / 'result.json')['status'], STATUS)


if __name__ == '__main__':
    unittest.main()
