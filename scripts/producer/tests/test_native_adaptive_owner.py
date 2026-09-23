"""Exercise actual native admission, sampling and durable adaptive-policy evidence."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from native_render_processes import ProcessIdentity
from native_render_resources import GIB, ResourcePolicy, ResourceSnapshot
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from test_native_render_policy import policy_snapshot
from test_native_render_resources import START


class NativeAdaptiveOwnerTests(unittest.TestCase):
    """Mock external processes; retain the real owner's policy and evidence paths."""

    def setUp(self) -> None:
        """Create non-media fixtures without a browser, encoder or real host lease."""
        temporary = tempfile.TemporaryDirectory(prefix='native-adaptive-owner-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        project, output = root / 'project', root / 'output'
        project.mkdir(); output.mkdir()
        cli, sandbox = root / 'cli.js', root / 'sandbox.sb'
        cli.write_text('TEST executable'); sandbox.write_text('TEST sandbox')
        self.settings = NativeRunConfig(project, output, cli, ['TEST-NO-LAUNCH'], {},
            {'output': str(output / 'result.bin'), 'sdkSha256': digest(cli),
             'sandboxSha256': digest(sandbox)}, sandbox=sandbox)
        self.baseline = replace(policy_snapshot(), measured_at=time.time() - 20)
        self.enterContext(patch('studio.native_run.NativeWorkLease.acquire', return_value=Mock()))
        self.enterContext(patch('builtins.print'))

    def close_owner(self, owner: NativeRun) -> None:
        """Release every test-owned file and restore the calling signal handlers."""
        owner.cleanup()
        owner.release_lease()
        for handle in (owner.log, owner.samples):
            if handle is not None:
                handle.close()
        owner.signal_handlers.restore()

    def prepare_owner(self, settings: NativeRunConfig | None = None,
                      baseline: ResourceSnapshot | None = None) -> NativeRun:
        """Run real prelaunch admission, then attach an explicitly fake live registry."""
        owner = NativeRun('TEST', settings or self.settings)
        self.addCleanup(self.close_owner, owner)
        with patch.object(owner, 'measure_resources', return_value=baseline or self.baseline):
            owner.prepare()
        owner.child = Mock(pid=100)
        owner.child.poll.return_value = None
        owner.registry = Mock(known={100: ProcessIdentity(100, START, 100)})
        owner.registry.cleanup.return_value = {'verified': True, 'TEST': 'mock child absent'}
        return owner

    def sample(self, owner: NativeRun, elapsed: float, changes: dict | None = None) -> None:
        """Supply actual successive telemetry values through the owner's sample method."""
        current = replace(self.baseline, measured_at=self.baseline.measured_at + 1 + elapsed,
                          **(changes or {}))
        with patch.object(owner, 'measure_resources', return_value=current), \
                patch('studio.native_run.time.monotonic', return_value=100 + elapsed):
            owner.sample()

    def receipt(self, owner: NativeRun) -> dict:
        """Read persisted JSON rather than checking only mutated in-memory state."""
        return json.loads(owner.path.read_text())

    def test_adaptive_default_records_capacity_derived_limits(self) -> None:
        """An absent explicit policy means a measured host-derived budget."""
        self.assertIsNone(self.settings.policy)
        owner = self.prepare_owner()
        receipt = self.receipt(owner)
        self.assertEqual(receipt['resourcePolicyMode'], 'capacity-adaptive-v1')
        self.assertEqual(receipt['baseline']['physical_bytes'], 64 * GIB)
        self.assertEqual(receipt['policy']['maximum_owned_gib'], 16)
        self.assertEqual(receipt['policy']['maximum_process_gib'], 8)
        self.assertEqual(receipt['policy']['maximum_swap_growth_gib'], 4)
        derivation = receipt['resourcePolicyDerivation']
        self.assertEqual(derivation['physicalBytes'], receipt['baseline']['physical_bytes'])
        self.assertEqual(derivation['budgets'], receipt['policy'])
        self.assertTrue(derivation['ownedBudgetRule'])
        self.assertTrue(derivation['literalUnusedRamAdvisory'])
        self.assertFalse(derivation['coarseHeadroomConvertedToBytes'])

    def test_healthy_4112_gib_tree_survives_actual_owner_sample(self) -> None:
        """The reported title-render footprint no longer hits the former 4 GiB default."""
        owner = self.prepare_owner()
        self.sample(owner, 0, {'owned_footprint_bytes': int(4.112 * GIB)})
        self.assertIsNone(owner.abort_reason)
        receipt = self.receipt(owner)
        self.assertIn('resourcePolicyEvaluation', receipt)
        self.assertFalse(receipt['resourcePolicyEvaluation']['stopReasons'])
        self.assertIn('guard', receipt['latestResourceSnapshot'])

    def test_sustained_warning_preserves_each_reading_and_final_reason(self) -> None:
        """Durable sample history distinguishes observed duration from instantaneous abort."""
        owner = self.prepare_owner()
        for elapsed in (0, 5):
            self.sample(owner, elapsed, {'kernel_pressure_level': 2})
            self.assertIsNone(owner.abort_reason)
        self.sample(owner, 10, {'kernel_pressure_level': 2})
        self.assertIsNotNone(owner.abort_reason)
        rows = [json.loads(line) for line in Path(owner.samples.name).read_text().splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual([row['guard']['conditions']['kernel-warning']['readings'] for row in rows], [1, 2, 3])
        self.assertFalse(rows[0]['guard']['stopReasons'])
        self.assertTrue(rows[-1]['guard']['stopReasons'])
        self.assertEqual(self.receipt(owner)['resourcePolicyEvaluation'], rows[-1]['guard'])

    def test_explicit_fixed_limit_is_not_silently_enlarged(self) -> None:
        """Callers intentionally passing 4 GiB retain the legacy immediate stop."""
        fixed = ResourcePolicy(maximum_owned_gib=4, maximum_process_gib=3,
                               maximum_swap_growth_gib=1)
        owner = self.prepare_owner(replace(self.settings, policy=fixed))
        self.assertEqual(self.receipt(owner)['policy']['maximum_owned_gib'], 4)
        self.sample(owner, 0, {'owned_footprint_bytes': int(4.112 * GIB)})
        self.assertIn('owned render footprint exceeds policy', owner.abort_reason)

    def test_adaptive_admission_does_not_reject_literal_unused_or_compressor_history(self) -> None:
        """The generic owner's default no longer needs a Short-specific advisory flag."""
        baseline = replace(self.baseline, unused_physical_bytes=GIB, compressor_bytes=30 * GIB,
                           swap_used_bytes=30 * GIB)
        owner = self.prepare_owner(baseline=baseline)
        self.assertFalse(self.settings.unused_ram_advisory)
        self.assertFalse(self.receipt(owner)['admissionReasons'])
        self.assertTrue(self.receipt(owner)['resourcePolicyDerivation']['admissionWarnings'])

    def test_observation_state_is_new_for_each_owner(self) -> None:
        """A new attempt cannot inherit the previous owner's warning window."""
        first = self.prepare_owner()
        self.sample(first, 0, {'kernel_pressure_level': 2})
        self.sample(first, 5, {'kernel_pressure_level': 2})
        another = self.settings.root / 'next'
        another.mkdir()
        settings = replace(self.settings, root=another, admission={**self.settings.admission,
                           'output': str(another / 'result.bin')})
        second = self.prepare_owner(settings)
        self.sample(second, 10, {'kernel_pressure_level': 2})
        self.assertIsNone(second.abort_reason)
        self.assertEqual(self.receipt(second)['resourcePolicyEvaluation']['conditions']['kernel-warning']['readings'], 1)


if __name__ == '__main__':
    unittest.main()
