"""Calibration orchestration refusal/retention tests, not measured service evidence."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from cut_preview_io import bound_json, write_new
from native_review_calibration import finish_session, record_failure, serial_runs
from native_review_calibration_worker import execute, require_provenance, require_session


class CalibrationOwnershipTests(unittest.TestCase):
    """Do not run generated media after a missing owner or erase completed attempts."""

    def setUp(self) -> None:
        """Use a new canonical scratch directory for each bounded behavior test."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def test_direct_worker_without_owner_refuses_before_media(self) -> None:
        """The public worker entry requires actual inspection launch environment."""
        with patch.dict(os.environ, {}, clear=True), patch('native_review_calibration_worker.prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'live owner'):
                execute(self.root / 'request.json')
        prepare.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_later_failure_keeps_first_success_in_manifest_inventory(self) -> None:
        """An in-place result list preserves preceding evidence when a later owner fails."""
        first = self.root / 'measurement.json'
        write_new(first, {'inspection': {'TEST': 'reference'}})
        row = {'id': 'serial-00', 'measurement': {'path': str(first)}}
        rows = []
        with patch('native_review_calibration.measure_once', side_effect=[row, RuntimeError('failed')]):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                serial_runs(self.root, {}, 2, rows)
        self.assertEqual(rows, [row])

    def test_failed_owner_is_retained_as_failure_not_service_sample(self) -> None:
        """Terminal failed ownership and concrete diagnostics survive the run."""
        owner = self.root / 'inspection.render.json'
        write_new(owner, {'status': 'failed', 'completedAt': 'TEST terminal'})
        row = record_failure(self.root, RuntimeError('TEST admission refused'))
        self.assertEqual(row['owner']['path'], str(owner))
        self.assertTrue(Path(row['diagnostic']['path']).is_file())
        self.assertNotIn('timing', row)

    def test_nonterminal_owner_is_never_called_a_failed_completion(self) -> None:
        """Keep diagnostics without fabricating a terminal owner after partial admission."""
        write_new(self.root / 'inspection.render.json', {'status': 'preparing'})
        row = record_failure(self.root, RuntimeError('TEST interrupted setup'))
        self.assertIsNone(row['owner'])
        self.assertTrue(Path(row['diagnostic']['path']).is_file())

    def test_copied_session_receipt_cannot_replace_released_live_lock(self) -> None:
        """An owner-admission snapshot is insufficient once the live session disappears."""
        with patch('native_work_pool_state.ledger'), \
                patch('native_work_pool_observe.observe', return_value=SimpleNamespace(session=None)), \
                patch('native_review_calibration_worker.host_identity', return_value={}), \
                patch('native_review_calibration_worker.active_owner_snapshot') as owner:
            with self.assertRaisesRegex(ValueError, 'session is no longer live'):
                require_session({'session': {'nonce': 'copied-old-nonce'}}, self.root / 'request.json')
        owner.assert_not_called()

    def test_session_cleanup_failure_keeps_success_inventory_and_diagnostic(self) -> None:
        """Closing the candidate session cannot hide prior work or its cleanup failure."""
        session = SimpleNamespace(close=Mock(side_effect=RuntimeError('TEST close failed')))
        manifest = {'runs': [{'id': 'completed-before-close'}], 'failures': []}
        with self.assertRaisesRegex(RuntimeError, 'close failed'):
            finish_session(session, self.root, manifest)
        value = bound_json(self.root / 'measurements.json')
        self.assertEqual(value['runs'], manifest['runs'])
        self.assertEqual(len(value['failures']), 1)
        self.assertTrue(Path(value['failures'][0]['diagnostic']['path']).is_file())

    def test_claimed_old_engine_refuses_before_media_or_tool_work(self) -> None:
        """The worker derives code identity rather than echoing parent provenance."""
        request = {'provenance': {'engine': {'identity': 'old'}, 'tools': {}, 'harness': {}}}
        with patch('native_review_calibration_worker.engine_record', return_value={'identity': 'current'}):
            with self.assertRaisesRegex(ValueError, 'engine provenance changed'):
                require_provenance(request)
