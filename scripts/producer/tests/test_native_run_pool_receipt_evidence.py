"""P0 adapter test (I-E23, P0 Step 3.7): an owner receipt carries the fields the pool-qualification evidence reads.

The owner goes through real pool admission with the harness of ``test_native_run_pool_admission`` (a private pool
namespace; only telemetry, the child and its registry are TEST doubles). Then one identity-bound TEST reading of the
TEST child (pid 100, START) goes through the real ``NativeRun.sample``, as ``test_native_render_cpu`` does. The
receipt's ``cpu`` block is never written by hand.

This deviates from the Step 3.7 text, which assumed ``cpu`` after a mocked-sample admission. NativeRun writes
``cpu`` only when it samples a live child (p0-records E-001; DECISION-LOG P0-M017-adapter-test-deviation). The test
has its own module so the taken 7dde85ba module keeps its size (G11). The harness adaptations there are in place:
``ProcessIdentity`` registry rows, the ``live_child`` and ``sample_patch`` hooks, src's queue record
``{ticket, attempts, queueSeconds, admitted}``, and src's no-retry-at-the-deadline rule.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import time
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_native_run_pool_admission as admission
from studio import pool_qualification_evidence as evidence
from studio.native_run import NativeRun
from test_native_render_cpu import advance, host, process

REAL_SAMPLE = NativeRun.sample  # the real method, kept before any test patches it


class ReceiptEvidenceTests(unittest.TestCase):
    """Top-level queueSeconds, pressureWaitSeconds and cpu reach ``pool_qualification_evidence._owner``."""

    setUp = admission.NativeRunPoolAdmissionTests.setUp
    execute = admission.NativeRunPoolAdmissionTests.execute
    receipt = admission.NativeRunPoolAdmissionTests.receipt

    def reading(self) -> object:
        """A fresh reading of exactly the TEST child, one second after the admission CPU reading."""
        child = process(100, 1.0, start=100.5)  # started after the admission reading; one CPU-second of its own
        return replace(self.snapshot, measured_at=time.time(), processes=(child,), owned_pids=(100,),
                       identity_verified=True, host_cpu=advance(host(100), 1, .25),
                       owned_footprint_bytes=child.footprint_bytes, largest_owned_process_bytes=child.footprint_bytes)

    def bound_sample(self, owner: NativeRun) -> None:
        """The real ``NativeRun.sample`` over the identity-bound TEST reading."""
        with patch.object(owner, 'measure_resources', return_value=self.reading()):
            REAL_SAMPLE(owner)

    def test_receipt_carries_the_fields_the_pool_evidence_reads(self) -> None:
        """Real admission and one real sample; the qualification reader gets numbers, never None."""
        self.snapshot = replace(self.snapshot, host_cpu=host(100))  # the admission baseline carries a CPU reading
        self.live_child, self.sample_patch = True, {'autospec': True, 'side_effect': self.bound_sample}
        run = NativeRun('evidence', self.settings)
        self.assertTrue(self.execute(run, lambda _seconds: None), self.receipt(run).get('abortReason'))
        receipt = self.receipt(run)
        self.assertIsInstance(receipt['queueSeconds'], float)
        self.assertIsInstance(receipt['pressureWaitSeconds'], float)
        self.assertEqual(receipt['cpu']['observedOwnedCpuSeconds'], 1.0)
        self.assertIs(receipt['leaseCleanupVerified'], True)
        row = evidence._owner(run.path)
        self.assertIsInstance(row['queueSeconds'], float)
        self.assertIsInstance(row['pressureWaitSeconds'], float)
        self.assertEqual(row['ownedCpuSeconds'], 1.0)
        self.assertIs(row['cleanupVerified'], True)


if __name__ == '__main__':
    unittest.main()
