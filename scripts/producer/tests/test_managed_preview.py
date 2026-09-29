"""Preview replacement and admission regressions without starting media."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import fcntl
import json
import os
import threading
import time
import unittest
from dataclasses import replace
from unittest import mock

import native_work_lease as work
from native_render_resources import GIB
from _native_pool_fixture import members
from _managed_preview_fixture import ManagedPreviewFixture
from _pending import pending
from studio import managed_preview as managed
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio.studio_server import ServerRecord, StudioServerError


class ManagedPreviewTests(ManagedPreviewFixture, unittest.TestCase):
    """Real private registry I/O with inert preview-process leaves."""

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
        new_runtime = self.checkout_runtime('checkout-a', 'TEST-identity-b')
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

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup (managed_preview.py:171-173); '
                   'P1 M-056 gives Studio its own pool class')
    def test_runtime_upgrade_does_not_wait_for_a_render(self) -> None:
        """Studio takes no pool slot: a render holding the heavy lane never delays a runtime upgrade."""
        first = self.open()
        self.mocks[6].return_value = self.checkout_runtime('checkout-a', 'TEST-identity-b')
        heavy = work.NativeWorkLease.acquire('heavy', str(self.projects[0]))
        try:
            with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
                upgraded = self.open(wait_seconds=0.5)
            self.assertNotIn(first.pid, self.identities)
            self.assertIn(upgraded.pid, self.identities)
            self.assertEqual(len(members(self.root / 'registry')), 1)  # only the render's own member
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
        self.assertFalse(self.heavy_fence())

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup (managed_preview.py:171-173); '
                   'P1 M-056 gives Studio its own pool class')
    def test_wrong_runtime_after_launch_is_stopped_by_identity_and_releases_the_lane(self) -> None:
        """A started server that fails verification is stopped exactly; no host-wide fence remains."""
        self.mocks[3].side_effect = lambda _cli, project, port, **options: self.launch(
            '/stock/hyperframes/dist/cli.js', project, port, **options)
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop, \
                self.assertRaisesRegex(StudioServerError, 'does not use the qualified'):
            self.open()
        stop.assert_called()
        self.assertEqual(self.identities, {})
        self.assertFalse(self.heavy_fence())
        value = json.loads(self.record(0).read_text())
        self.assertEqual(value['state'], 'stopped')
        self.assertTrue(value['cleanup']['verified'])
        self.mocks[3].side_effect = self.launch
        self.assertIn(self.open().pid, self.identities)

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup (managed_preview.py:171-173); '
                   'P1 M-056 gives Studio its own pool class')
    def test_unverified_stop_of_a_failed_launch_fences_this_project_with_its_identity(self) -> None:
        """A survivor keeps only this project fenced, recorded so an operator can clear it once it exits."""
        self.mocks[3].side_effect = lambda _cli, project, port, **options: self.launch(
            '/stock/hyperframes/dist/cli.js', project, port, **options)
        with mock.patch.object(state, 'terminate_tree', side_effect=lambda value: dict(
                verified=False, survivors=state.live_owned(value), signals=[])), \
                self.assertRaisesRegex(StudioServerError, 'does not use the qualified'):
            self.open()
        fence = json.loads(self.record(0).read_text())
        self.assertEqual(fence['state'], 'launching')
        self.assertEqual([row['pid'] for row in fence['processes']], list(self.identities))
        self.assertFalse(self.heavy_fence())

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup (managed_preview.py:171-173); '
                   'P1 M-056 gives Studio its own pool class')
    def test_handled_startup_failure_with_its_reaped_child_releases_the_lane(self) -> None:
        """The launcher reaped its own child: verified absent, so only nothing stays fenced."""
        def failed(_cli: str, _project: str, _port: int, **_options: object) -> ServerRecord:
            error = StudioServerError('TEST Studio preview exited before readiness')
            error.preview_pid = 24999
            raise error
        self.mocks[3].side_effect = failed
        with self.assertRaisesRegex(StudioServerError, 'exited before readiness'):
            self.open()
        self.assertFalse(self.heavy_fence())
        self.assertEqual(json.loads(self.record(0).read_text())['cleanup']['reason'], 'launched preview already exited')
        self.mocks[3].side_effect = self.launch
        self.assertIn(self.open().pid, self.identities)

    def test_opening_another_project_keeps_the_first_view_running(self) -> None:
        """A second reviewer's project never stops, switches or retargets the first view."""
        first = self.open()
        with mock.patch.object(state.os, 'kill') as stop:
            second = self.open(1)
            self.assertEqual(self.open(), first)
        stop.assert_not_called()
        self.assertIn(first.pid, self.identities)
        self.assertIn(second.pid, self.identities)
        self.assertEqual(self.mocks[3].call_count, 2)
        listed = {row['preview']['project']: row['live'] for row in managed.list_previews()}
        self.assertEqual(listed, {str(self.projects[0]): True, str(self.projects[1]): True})

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup (managed_preview.py:171-173); '
                   'P1 M-056 gives Studio its own pool class')
    def test_busy_heavy_lane_does_not_block_another_projects_view(self) -> None:
        """A render in progress neither delays nor disturbs Studio for another project."""
        first = self.open()
        heavy = work.NativeWorkLease.acquire('heavy', str(self.projects[0]))
        try:
            second = self.open(1, wait_seconds=0.5)
            self.assertIn(first.pid, self.identities)
            self.assertIn(second.pid, self.identities)
            heavy.complete()
        finally:
            heavy.close()

    def test_pressure_refuses_spawn_and_releases_unused_reservation(self) -> None:
        """Admission failure launches no process and leaves no phantom heavy job."""
        self.mocks[1].return_value = replace(self.snapshot, kernel_pressure_level=2)
        with self.assertRaisesRegex(StudioServerError, 'admission refused'):
            self.open()
        self.mocks[3].assert_not_called()
        self.assertFalse(self.heavy_fence())

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
        self.assertFalse(self.heavy_fence())

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
            self.assertFalse(self.heavy_fence())
            self.assertFalse(self.record(0).exists())

    def test_failed_cleanup_keeps_record_and_refuses_replacement(self) -> None:
        """A stubborn server of the same project cannot be forgotten while launching its successor."""
        first = self.open()
        self.mocks[6].return_value = self.checkout_runtime('checkout-a', 'TEST-identity-b')
        with mock.patch.object(state, 'terminate_tree', return_value={'verified': False}):
            with self.assertRaisesRegex(StudioServerError, 'did not exit'):
                self.open()
        registry = json.loads(self.record(0).read_text())
        self.assertEqual(registry['identity']['pid'], first.pid)
        self.assertEqual(registry['state'], 'running')
        self.assertEqual(self.mocks[3].call_count, 1)

    def test_reused_pid_is_never_signalled(self) -> None:
        """A different start identity remains untouched even for the same command."""
        first = self.open()
        self.identities[first.pid]['started'] = 'Wed Sep  9 12:00:00 2026'
        with mock.patch.object(state.os, 'kill') as stop:
            managed.stop_preview(str(self.projects[0]))
            self.open(1)
        stop.assert_not_called()

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup (managed_preview.py:171-173); '
                   'P1 M-056 gives Studio its own pool class')
    def test_startup_failure_is_unverified_until_no_process_of_it_is_found(self) -> None:
        """A launcher error is no proof that no child survived; the next open looks for survivors."""
        self.mocks[3].side_effect = RuntimeError('TEST uncertain startup')
        with self.assertRaisesRegex(RuntimeError, 'uncertain startup'):
            self.open()
        fence = json.loads(self.record(0).read_text())
        self.assertEqual((fence['state'], fence['cleanup']['reason']), ('launching', 'launched process identity unknown'))
        self.assertFalse(self.heavy_fence())  # the fence is this project's, never the host pool's
        self.mocks[3].side_effect = self.launch
        with mock.patch.object(state.os, 'kill') as stop:
            self.assertIn(self.open().pid, self.identities)
        stop.assert_not_called()
        self.assertEqual(json.loads(self.record(0).read_text())['state'], 'running')

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


    def test_capacity_bound_names_every_running_view_and_stops_nothing(self) -> None:
        """Beyond the bound a clear refusal lists the views; stopping one frees exactly one slot."""
        opened = [self.open(index) for index in range(registry.MAX_MANAGED_PREVIEWS)]
        with mock.patch.object(state.os, 'kill') as stop, \
                self.assertRaisesRegex(StudioServerError, 'limit of 6 views reached') as refused:
            self.open(registry.MAX_MANAGED_PREVIEWS)
        stop.assert_not_called()
        for project in self.projects[:registry.MAX_MANAGED_PREVIEWS]:
            self.assertIn(str(project), str(refused.exception))
        self.assertTrue(all(record.pid in self.identities for record in opened))
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            managed.stop_preview(str(self.projects[0]))
        self.assertIn(self.open(registry.MAX_MANAGED_PREVIEWS).pid, self.identities)
        self.assertTrue(all(record.pid in self.identities for record in opened[1:]))

    def test_legacy_single_slot_view_is_adopted_and_survives_other_opens(self) -> None:
        """A user's view registered by earlier code keeps running while reviewers open others."""
        user = self.launch(self.cli, str(self.projects[0]), 3991, open_browser=False)
        legacy = {'schemaVersion': 1, 'state': 'running', 'project': str(self.projects[0]),
                  'record': user.to_json(), 'identity': self.identities[user.pid]}
        (self.root / 'registry').mkdir(mode=0o700, exist_ok=True)
        (self.root / 'registry/preview.json').write_text(json.dumps(legacy))
        (self.root / 'registry/preview.json').chmod(0o600)  # As the earlier durable writer left it.
        with mock.patch.object(state.os, 'kill') as stop:
            self.open(1)
            self.open(2)
            self.assertEqual(self.open(), user)
        stop.assert_not_called()
        adopted = json.loads(self.record(0).read_text())
        self.assertEqual(adopted['adoptedFrom'], 'legacy-single-slot-registry')
        self.assertEqual(json.loads((self.root / 'registry/preview.json').read_text()), legacy,
                         'the legacy record is never rewritten')
        self.assertEqual(self.mocks[3].call_count, 2, 'the adopted user view was reused, not relaunched')

    def test_registry_wait_is_bounded_by_the_caller(self) -> None:
        """A stuck registry transaction refuses at the caller deadline and changes nothing."""
        self.open(0)
        lock = registry.native_work_lease.state_root() / registry.REGISTRY_DIR / 'registry.lock'
        held = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(held, fcntl.LOCK_EX)
            started = time.monotonic()
            with self.assertRaisesRegex(StudioServerError, 'before this call deadline'):
                managed.open_preview(str(self.projects[1]), 3991, wait_seconds=0.3)
            self.assertLess(time.monotonic() - started, 2)
        finally:
            os.close(held)
        self.assertEqual(self.mocks[3].call_count, 1)

    @pending('P1', 'capacityClock C1: src takes a heavy slot at Studio startup (managed_preview.py:171-173); '
                   'P1 M-056 gives Studio its own pool class')
    def test_reviewers_open_concurrently_while_an_export_runs_and_mappings_stay_current(self) -> None:
        """Two reviewers, one running export and an existing user view: nothing switches or stops.

        Studio takes no pool slot, so reviewers open while the export holds the heavy lane.
        """
        media = [self.root / f'review-{index}.mp4' for index in range(3)]
        for index, file in enumerate(media):
            file.write_bytes(f'TEST review mp4 {index}'.encode())
        user = managed.open_preview(str(self.projects[0]), 3990, media[0])
        (self.root / 'exporting-project').mkdir()
        export = work.NativeWorkLease.acquire('heavy', str(self.root / 'exporting-project'))
        results: dict[int, object] = {}

        def review(index: int) -> None:
            try:
                results[index] = managed.open_preview(str(self.projects[index]), 3990 + index, media[index], 20.0)
            except Exception as error:  # noqa: BLE001 - recorded for the assertions below.
                results[index] = error

        with mock.patch.object(state.os, 'kill') as stop:
            started = time.monotonic()
            self.run_threads(review, (1, 2))
            self.assertLess(time.monotonic() - started, 10)
            export.complete()
            export.close()
        stop.assert_not_called()
        self.assertTrue(all(isinstance(results[index], ServerRecord) for index in (1, 2)))
        views = {row['preview']['project']: row for row in managed.list_previews()}
        for index in range(3):
            row = views[str(self.projects[index])]
            self.assertTrue(row['live'] and row['media']['current'])
            self.assertEqual(row['media']['path'], str(media[index].resolve()))
        self.assertEqual(views[str(self.projects[0])]['preview']['identity']['pid'], user.pid)
        media[1].write_bytes(b'TEST replaced review bytes')
        self.assertFalse(managed.preview_status(str(self.projects[1]))['media']['current'])
        newer = self.root / 'review-1-v2.mp4'
        newer.write_bytes(b'TEST newer review mp4')
        self.assertEqual(managed.open_preview(str(self.projects[1]), 3991, newer), results[1])
        self.assertTrue(managed.preview_status(str(self.projects[1]))['media']['current'])
        self.assertEqual(self.mocks[3].call_count, 3)

    def run_threads(self, action: object, indexes: tuple[int, ...]) -> None:
        """Start every reviewer before joining any of them."""
        threads = [threading.Thread(target=action, args=(index,)) for index in indexes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)


if __name__ == '__main__':
    unittest.main()
