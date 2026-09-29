"""A worker's owner read survives the owner's own atomic publication, and nothing else.

F0 spike (1 of 25 worker starts): the worker opened ``<label>.render.json`` just before
``NativeRun.persist`` renamed a new snapshot over it, so ``read_bytes`` saw link count
0 and the healthy worker refused. These tests drive the real publisher and reader.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from cut_preview_io import ArtifactReplaced, read_bytes
from studio.native_export import (OWNER_ENV, OWNER_READ_ATTEMPTS, PID_ENV, REQUEST_ENV,
                                  active_owner_snapshot, require_owned_worker)
from studio.native_run import NativeRun
from studio.native_runtime import digest

REAL_OPEN, REAL_READ = os.open, os.read


class OwnerSnapshotRaceTests(unittest.TestCase):
    """Replace the receipt at exact points inside one read; never launch a worker."""

    def setUp(self) -> None:
        """Publish an owner receipt through the real NativeRun snapshot writer."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.owner = NativeRun.__new__(NativeRun)
        self.owner.path, self.owner.receipt_owned = self.root / 'owner.render.json', False
        self.owner.result = {'status': 'preparing', 'version': 0}
        self.owner.persist(initial=True)
        self.opens = 0

    def publish(self) -> None:
        """Persist the next complete snapshot exactly as a running owner does."""
        self.owner.result = {**self.owner.result, 'status': 'running',
                             'version': self.owner.result['version'] + 1}
        self.owner.persist()

    def open_hook(self, publish_on: set[int] | None) -> object:
        """Count owner opens; publish right after the numbered ones (None: every one)."""
        def opened(path: object, flags: int, *args: object) -> int:
            """Open for real, then publish when this owner open is selected."""
            descriptor = REAL_OPEN(path, flags, *args)
            if Path(path) == self.owner.path:
                self.opens += 1
                if publish_on is None or self.opens in publish_on:
                    self.publish()
            return descriptor
        return opened

    def test_owner_published_between_open_and_read_is_reopened(self) -> None:
        """The spike's failure: the reader sees an unlinked receipt and must reopen, not refuse."""
        with patch('cut_preview_io.os.open', side_effect=self.open_hook({1})):
            value = active_owner_snapshot(self.owner.path)
        self.assertEqual((value, self.opens), ({'status': 'running', 'version': 1}, 2))
        with patch('cut_preview_io.os.open', side_effect=self.open_hook({3})), \
                self.assertRaisesRegex(ArtifactReplaced, 'replaced at its path before it was read'):
            read_bytes(self.owner.path)

    def test_owner_published_after_the_bytes_were_read_is_never_returned(self) -> None:
        """Bytes of the replaced receipt are discarded; only the new snapshot is returned."""
        def read_then_publish(descriptor: int, size: int) -> bytes:
            """Return the real bytes, then publish once before the final identity check."""
            data = REAL_READ(descriptor, size)
            if self.owner.result['version'] == 0:
                self.publish()
            return data
        with patch('cut_preview_io.os.read', side_effect=read_then_publish), \
                patch('cut_preview_io.os.open', side_effect=self.open_hook(set())):
            self.assertEqual(active_owner_snapshot(self.owner.path), {'status': 'running', 'version': 1})
        self.assertEqual(self.opens, 2)

    def test_continuous_publication_is_bounded(self) -> None:
        """A receipt replaced on every read fails after the bounded attempts, never stale."""
        with patch('cut_preview_io.os.open', side_effect=self.open_hook(None)), \
                self.assertRaises(ArtifactReplaced):
            active_owner_snapshot(self.owner.path)
        self.assertEqual(self.opens, OWNER_READ_ATTEMPTS)

    def test_other_anomalies_fail_closed_on_the_first_read(self) -> None:
        """In-place rewrite, a second link and a deleted receipt are not replacements."""
        def rewrite_in_place(descriptor: int, size: int) -> bytes:
            """Return the real bytes, then rewrite the same inode as no owner ever does."""
            data = REAL_READ(descriptor, size)
            self.owner.path.write_text('{"status":"running","forged":true}')
            return data
        with patch('cut_preview_io.os.read', side_effect=rewrite_in_place), \
                patch('cut_preview_io.os.open', side_effect=self.open_hook(set())), \
                self.assertRaisesRegex(RuntimeError, 'changed during read') as caught:
            active_owner_snapshot(self.owner.path)
        self.assertNotIsInstance(caught.exception, ArtifactReplaced)
        os.link(self.owner.path, self.root / 'second-link.json')
        with self.assertRaisesRegex(RuntimeError, 'link count'):
            active_owner_snapshot(self.owner.path)
        (self.root / 'second-link.json').unlink()
        self.opens = 0
        with patch('cut_preview_io.os.open', side_effect=self.unlink_after_open), \
                self.assertRaisesRegex(RuntimeError, 'link count') as caught:
            active_owner_snapshot(self.owner.path)
        self.assertNotIsInstance(caught.exception, ArtifactReplaced)
        self.assertEqual(self.opens, 1)

    def unlink_after_open(self, path: object, flags: int, *args: object) -> int:
        """Delete (not replace) the receipt the reader has just opened."""
        descriptor = REAL_OPEN(path, flags, *args)
        if Path(path) == self.owner.path:
            self.opens += 1
            self.owner.path.unlink()
        return descriptor

    def test_export_worker_binding_survives_its_owners_publication(self) -> None:
        """The shared export worker check reads the new snapshot and still binds the request."""
        request_file = self.root / 'export-request.json'
        request = {'project': str(self.root / 'project'), 'output': str(self.root)}
        request_file.write_text(json.dumps(request))
        self.owner.result = {**self.owner.result, 'project': request['project'],
                             'additionalFilePinsBefore': {str(request_file): digest(request_file)}}
        self.publish()
        environment = {REQUEST_ENV: str(request_file), OWNER_ENV: str(self.owner.path), PID_ENV: str(os.getpid())}
        with patch.dict('os.environ', environment, clear=True), \
                patch('cut_preview_io.os.open', side_effect=self.open_hook({1})):
            require_owned_worker(request)
        self.assertEqual(self.opens, 2)

    def test_inspection_worker_binding_survives_its_owners_publication(self) -> None:
        """studio/owned_inspection uses the same reader for its live owner."""
        from studio.owned_inspection import require_worker
        worker, request_file = self.root / 'worker.py', self.root / 'request.json'
        worker.write_text('# TEST inspection worker, never executed\n')
        request = {'project': str(self.root / 'project'), 'pins': {str(worker): digest(worker)}}
        request_file.write_text(json.dumps(request))
        owner = self.root / 'inspection.render.json'
        self.owner.path.rename(owner)
        self.owner.path = owner
        self.owner.result = {**self.owner.result, 'project': request['project'],
                             'output': str(self.root / 'result.json'),
                             'args': [sys.executable, '-B', str(worker), '--worker', str(request_file)],
                             'additionalFilePinsBefore': {str(request_file): digest(request_file),
                                                          str(worker): digest(worker)}}
        self.publish()
        environment = {'SNIPER_INSPECTION_REQUEST': str(request_file), 'SNIPER_INSPECTION_OWNER': str(owner),
                       'SNIPER_INSPECTION_PID': str(os.getpid())}
        with patch.dict('os.environ', environment, clear=True), \
                patch('cut_preview_io.os.open', side_effect=self.open_hook({1})):
            self.assertEqual(require_worker(request_file, worker), request)
        self.assertEqual(self.opens, 2)


if __name__ == '__main__':
    unittest.main()
