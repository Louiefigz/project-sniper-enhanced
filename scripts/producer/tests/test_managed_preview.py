"""Preview replacement and admission regressions without starting media."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import native_work_lease as work
from native_render_resources import GIB, ProcessRequest, parse_snapshot
from test_native_render_resources import raw_sample
from studio import managed_preview as managed
from studio import managed_preview_state as state
from studio.studio_server import ServerRecord, StudioServerError


class ManagedPreviewTests(unittest.TestCase):
    """Real private registry I/O with inert preview-process leaves."""

    def setUp(self) -> None:
        """Create two native draft folders and isolate all global runtime state."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.projects = [self.root / name for name in ('draft-one', 'draft-two')]
        for project in self.projects:
            project.mkdir()
            (project / 'index.html').write_text('<html>TEST native source</html>')
        self.identities = {}
        self.next_pid = 24500
        self.runtime = self.root / 'qualified/hyperframes'
        self.cli = str(self.runtime / 'dist/cli.js')
        self.snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        patches = [mock.patch.object(work, 'state_root', return_value=self.root / 'registry'),
                   mock.patch.object(managed, 'read_snapshot', return_value=self.snapshot),
                   mock.patch.object(managed, 'adaptive_admission_reasons',
                                     wraps=managed.adaptive_admission_reasons),
                   mock.patch.object(managed, 'launch_preview', side_effect=self.launch),
                   mock.patch.object(state, 'process_identity', side_effect=lambda pid: self.identities.get(pid)),
                   mock.patch.object(state, 'read_tree_table', side_effect=self.tree),
                   mock.patch.object(managed, 'install_runtime', return_value=self.runtime)]
        self.mocks = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)

    def tree(self) -> dict:
        """Expose only inert fixture identities to the real ancestry algorithm."""
        return {pid: (1, row['pgid'], row['started']) for pid, row in self.identities.items()}

    def launch(self, cli: str, project: str, port: int, **options: object) -> ServerRecord:
        """Create an inert exact preview identity; never call subprocess.Popen."""
        self.assertFalse(options['open_browser'])
        self.next_pid += 1
        pid = self.next_pid
        self.identities[pid] = dict(pid=pid, pgid=pid, started='Wed Sep  9 11:00:00 2026',
            command=f'node {cli} preview {project} --port {port} --foreground --json')
        return ServerRecord(port, pid, f'http://127.0.0.1:{port}', 'TEST')

    def open(self, index: int = 0) -> ServerRecord:
        """Use real manager/lease/registry logic for a fixture draft."""
        return managed.open_preview(str(self.projects[index]), 3990 + index)

    def stop_signal(self, pid: int, selected: object) -> None:
        """Simulate only the addressed inert server exiting on its signal."""
        self.identities.pop(pid)

    def test_same_draft_reuses_exact_live_server(self) -> None:
        """Repeated open cannot accumulate a second preview or new browser."""
        first = self.open()
        self.assertEqual(first, self.open())
        self.assertEqual(self.mocks[3].call_count, 1)
        self.assertEqual(self.mocks[3].call_args.args[0], self.cli)
        self.assertEqual(self.mocks[6].call_count, 2)

    def test_adopted_stock_server_is_replaced_with_current_qualified_runtime(self) -> None:
        """Stock adoption retains cleanup authority without qualifying later reuse."""
        project = str(self.projects[0])
        old = self.launch('/stock/hyperframes/dist/cli.js', project, 3990, open_browser=False)
        managed.adopt_preview(project, old)
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            current = self.open()
        self.assertNotEqual(current.pid, old.pid)
        self.assertNotIn(old.pid, self.identities)
        self.assertEqual(self.mocks[3].call_args.args[0], self.cli)

    def test_old_qualified_runtime_is_replaced_after_manifest_changes(self) -> None:
        """A content-addressed runtime update invalidates same-project process reuse."""
        old = self.open()
        new_runtime = self.root / 'qualified-new/hyperframes'
        self.mocks[6].return_value = new_runtime
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            current = self.open()
        self.assertNotIn(old.pid, self.identities)
        self.assertNotEqual(current.pid, old.pid)
        self.assertEqual(self.mocks[3].call_args.args[0], str(new_runtime / 'dist/cli.js'))

    def test_unregistered_stock_server_is_owned_before_replacement(self) -> None:
        """A legacy per-project record cannot bypass runtime verification or cleanup."""
        project = str(self.projects[0])
        old = self.launch('/stock/hyperframes/dist/cli.js', project, 3990, open_browser=False)
        with mock.patch.object(managed, 'read_record', return_value=old), \
                mock.patch.object(managed, 'is_live_preview', return_value=True), \
                mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            current = self.open()
        self.assertNotIn(old.pid, self.identities)
        self.assertNotEqual(current.pid, old.pid)
        self.assertEqual(len(self.identities), 1)

    def test_unregistered_current_runtime_is_reused(self) -> None:
        """Recover a current per-project preview without spawning a duplicate."""
        project = str(self.projects[0])
        existing = self.launch(self.cli, project, 3990, open_browser=False)
        with mock.patch.object(managed, 'read_record', return_value=existing), \
                mock.patch.object(managed, 'is_live_preview', return_value=True):
            self.assertEqual(self.open(), existing)
        self.mocks[3].assert_not_called()

    def test_busy_heavy_lane_preserves_same_project_old_runtime(self) -> None:
        """Runtime upgrades wait for media ownership before stopping the old preview."""
        first = self.open()
        self.mocks[6].return_value = self.root / 'qualified-new/hyperframes'
        heavy = work.NativeWorkLease.acquire('heavy', str(self.projects[0]))
        try:
            with self.assertRaises(work.NativeWorkBusy), mock.patch.object(state.os, 'kill') as stop:
                self.open()
            stop.assert_not_called()
            self.assertIn(first.pid, self.identities)
            self.assertEqual(self.mocks[3].call_count, 1)
            heavy.complete()
        finally:
            heavy.close()

    def test_runtime_verification_failure_preserves_current_preview(self) -> None:
        """Corrupt or unsupported SDK bytes cannot trigger a stock fallback or teardown."""
        first = self.open()
        self.mocks[6].side_effect = ValueError('Installed native runtime changed')
        with self.assertRaisesRegex(ValueError, 'runtime changed'), mock.patch.object(state.os, 'kill') as stop:
            self.open()
        stop.assert_not_called()
        self.assertIn(first.pid, self.identities)
        self.assertEqual(self.mocks[3].call_count, 1)
        self.assertFalse((self.root / 'registry/heavy.active.json').exists())

    def test_wrong_runtime_after_launch_keeps_unverified_fence(self) -> None:
        """Do not publish readiness if the launched process points at another SDK."""
        self.mocks[3].side_effect = lambda _cli, project, port, **options: self.launch(
            '/stock/hyperframes/dist/cli.js', project, port, **options)
        with self.assertRaisesRegex(StudioServerError, 'does not use the qualified'):
            self.open()
        self.assertTrue((self.root / 'registry/heavy.active.json').exists())
        value = json.loads((self.root / 'registry/preview.json').read_text())
        self.assertEqual(value['state'], 'launching')

    def test_new_draft_waits_for_old_exit_before_launch(self) -> None:
        """Replacement must remove the old identity before spawning the new one."""
        first = self.open()
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            second = self.open(1)
        stop.assert_called_once()
        self.assertNotIn(first.pid, self.identities)
        self.assertIn(second.pid, self.identities)
        self.assertEqual(len(self.identities), 1)

    def test_busy_heavy_lane_preserves_current_preview(self) -> None:
        """Do not tear down the user's preview before discovering a busy render."""
        first = self.open()
        heavy = work.NativeWorkLease.acquire('heavy', str(self.projects[0]))
        try:
            with self.assertRaises(work.NativeWorkBusy):
                self.open(1)
            self.assertIn(first.pid, self.identities)
            self.assertEqual(self.mocks[3].call_count, 1)
            heavy.complete()
        finally:
            heavy.close()

    def test_pressure_refuses_spawn_and_releases_unused_reservation(self) -> None:
        """Admission failure launches no process and leaves no phantom heavy job."""
        self.mocks[1].return_value = replace(self.snapshot, kernel_pressure_level=2)
        with self.assertRaisesRegex(StudioServerError, 'admission refused'):
            self.open()
        self.mocks[3].assert_not_called()
        self.assertFalse((self.root / 'registry/heavy.active.json').exists())

    def test_normal_large_host_admits_cache_and_compression_without_rebuilding(self) -> None:
        """Preview startup shares export's measured admission instead of a literal-free gate."""
        self.mocks[1].return_value = replace(self.snapshot, unused_physical_bytes=GIB,
            compressor_bytes=30 * GIB, swap_used_bytes=30 * GIB)
        original = (self.projects[0] / 'index.html').read_bytes()
        record = self.open()
        self.assertIn(record.pid, self.identities)
        self.assertEqual(self.mocks[3].call_count, 1)
        policy = self.mocks[2].call_args.args[1]
        self.assertEqual(policy.maximum_owned_gib, 16)
        self.assertEqual(policy.maximum_process_gib, 8)
        self.assertEqual((self.projects[0] / 'index.html').read_bytes(), original)
        self.assertFalse((self.root / 'registry/heavy.active.json').exists())

    def test_shared_admission_rejects_unsafe_or_stale_readings_before_spawn(self) -> None:
        """Relaxing historical cache/compression limits preserves active host safety gates."""
        cases = [('kernel_pressure_level', 4), ('free_percent', 24.9),
                 ('disk_free_bytes', 9 * GIB), ('free_percent', float('nan')),
                 ('measured_at', self.snapshot.measured_at - 60)]
        for field, value in cases:
            self.mocks[1].return_value = replace(self.snapshot, **{field: value})
            with self.subTest(field=field, value=value), \
                    self.assertRaisesRegex(StudioServerError, 'admission refused'):
                self.open()
            self.mocks[3].assert_not_called()
            self.assertFalse((self.root / 'registry/heavy.active.json').exists())
            self.assertFalse((self.root / 'registry/preview.json').exists())

    def test_failed_cleanup_keeps_record_and_refuses_replacement(self) -> None:
        """A stubborn server cannot be forgotten while launching another."""
        first = self.open()
        with mock.patch.object(state, 'terminate_tree', return_value={'verified': False}):
            with self.assertRaisesRegex(StudioServerError, 'did not exit'):
                self.open(1)
        registry = json.loads((self.root / 'registry/preview.json').read_text())
        self.assertEqual(registry['identity']['pid'], first.pid)
        self.assertEqual(self.mocks[3].call_count, 1)

    def test_reused_pid_is_never_signalled(self) -> None:
        """A different start identity remains untouched even for the same command."""
        first = self.open()
        self.identities[first.pid]['started'] = 'Wed Sep  9 12:00:00 2026'
        with mock.patch.object(state.os, 'kill') as stop:
            self.open(1)
        stop.assert_not_called()

    def test_startup_failure_preserves_unverified_fence(self) -> None:
        """A launcher error cannot be interpreted as proof that no child survived."""
        self.mocks[3].side_effect = RuntimeError('TEST uncertain startup')
        with self.assertRaisesRegex(RuntimeError, 'uncertain startup'):
            self.open()
        self.assertTrue((self.root / 'registry/heavy.active.json').exists())
        with self.assertRaisesRegex(StudioServerError, 'unverified'):
            self.open()

    def test_adoption_keeps_existing_server_and_composition_bytes(self) -> None:
        """The live user preview can enter management without a restart or encode."""
        project = str(self.projects[0])
        record = self.launch(self.cli, project, 41058, open_browser=False)
        before = (self.projects[0] / 'index.html').read_bytes()
        managed.adopt_preview(project, record)
        self.assertEqual(record, self.open())
        self.mocks[3].assert_not_called()
        self.assertEqual(before, (self.projects[0] / 'index.html').read_bytes())

    def test_other_project_stop_does_not_touch_active_preview(self) -> None:
        """A stop command for an old draft cannot stop the current draft."""
        first = self.open()
        with mock.patch.object(state.os, 'kill') as stop:
            managed.stop_preview(str(self.projects[1]))
        stop.assert_not_called()
        self.assertIn(first.pid, self.identities)

    def test_repeated_adoption_retains_a_reparented_child(self) -> None:
        """Fresh root ancestry must not erase an earlier detached-child witness."""
        first = self.open()
        child = dict(pid=24599, pgid=24599, started='Wed Sep  9 11:00:01 2026', command='TEST child')
        self.identities[child['pid']] = child
        table = self.tree()
        table[child['pid']] = (first.pid, child['pgid'], child['started'])
        with mock.patch.object(state, 'read_tree_table', return_value=table):
            managed.preview_status(str(self.projects[0]))
        managed.adopt_preview(str(self.projects[0]), first)
        registry = managed.preview_status(str(self.projects[0]))['preview']
        self.assertIn(child['pid'], [row['pid'] for row in registry['processes']])


if __name__ == '__main__':
    unittest.main()
