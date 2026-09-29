"""Studio startup never holds a host-pool slot: no stranded fence, no waiting behind any native work."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
from _native_pool_fixture import members, qualify_fixture_host
from _pending import pending
from native_render_resources import GIB, ProcessRequest, parse_snapshot
from native_work_pool import PoolRequest, admit
from native_work_pool_state import NativeWorkQueued
from studio import managed_preview as managed
from studio import managed_preview_state as state
from studio.studio_server import ServerRecord, StudioServerError
from test_native_render_resources import raw_sample


class StudioStartupPoolTests(unittest.TestCase):
    """Real manager, launcher tagging and pool code in a private namespace; the child is TEST."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.projects = {}
        for name in ('clip-a', 'clip-b', 'clip-c'):
            (self.root / name).mkdir()
            (self.root / name / 'index.html').write_text('<html>TEST native source</html>')
            self.projects[name] = str(self.root / name)
        self.runtime = self.root / 'qualified/hyperframes'
        (self.runtime / 'dist').mkdir(parents=True)
        (self.runtime / 'dist/cli.js').write_text('// TEST CLI, never executed')
        self.identities = {}
        snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        for patch in (mock.patch.object(work, 'state_root', return_value=self.root / 'registry'),
                      mock.patch.object(managed, 'read_snapshot', return_value=snapshot),
                      mock.patch.object(managed, 'install_runtime', return_value=self.runtime),
                      mock.patch.object(state, 'process_identity', side_effect=lambda pid: self.identities.get(pid)),
                      mock.patch.object(state, 'read_tree_table',
                                        side_effect=lambda: {pid: (1, row['pgid'], row['started'])
                                                             for pid, row in self.identities.items()})):
            patch.start()
            self.addCleanup(patch.stop)

    def launch(self, cli: str, project: str, port: int, **_options: object) -> ServerRecord:
        """An inert TEST server identity; nothing is executed."""
        pid = 24600 + len(self.identities)
        self.identities[pid] = dict(pid=pid, pgid=pid, started='Wed Sep  9 11:00:00 2026',
                                    command=f'node {cli} preview {project} --port {port} --foreground --json')
        return ServerRecord(port, pid, f'http://127.0.0.1:{port}', 'TEST')

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup')
    def test_a_failure_before_spawning_leaves_no_fence(self) -> None:
        with mock.patch.dict(os.environ, {'HYPERFRAME_RUNTIME_URL': 'http://127.0.0.1:9/TEST'}):
            with self.assertRaisesRegex(StudioServerError, 'unsupported Studio runtime override'):
                managed.open_preview(self.projects['clip-a'], 3990, None, 2)
        self.assertEqual(members(self.root / 'registry'), [])
        with mock.patch.object(managed, 'launch_preview', side_effect=self.launch):
            self.assertIn(managed.open_preview(self.projects['clip-a'], 3990, None, 2).pid, self.identities)

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup')
    def test_studio_opens_while_every_heavy_slot_is_busy_and_owners_queue(self) -> None:
        qualify_fixture_host(self, {'heavy': 2, 'audio': 1})
        leases = [work.NativeWorkLease.acquire('heavy', self.projects['clip-b']) for _ in range(2)]
        audio = work.NativeWorkLease.acquire('audio', self.projects['clip-b'])
        waiting = PoolRequest('heavy', self.projects['clip-c'], declares_launch=True)
        with self.assertRaises(NativeWorkQueued):
            admit('heavy', self.projects['clip-c'], waiting)          # an export owner queued for heavy
        try:
            with mock.patch.object(managed, 'launch_preview', side_effect=self.launch):
                record = managed.open_preview(self.projects['clip-a'], 3990, None, 2)
            self.assertIn(record.pid, self.identities)
            self.assertEqual(sorted(json.loads(row.read_text())['class'] for row in members(self.root / 'registry')),
                             ['audio', 'heavy', 'heavy'])            # Studio took no slot of its own
        finally:
            waiting.withdraw()
            for lease in (*leases, audio):
                lease.complete()
                lease.close()

if __name__ == '__main__':
    unittest.main()
