"""Recovering a quarantined Studio member needs evidence that its start is over (X244 M1, G9; and m1, m5).

The Studio manager, registry and pool run for real through ManagedPreviewFixture (inert TEST preview identities;
no process starts) on a TEST schema-1 record, as in test_managed_preview_studio_release. A failed start whose
survivors are known records them on its quarantined member (phase 'launching'), so recovery by nonce refuses while
any of them lives. When they are unknown (the launched PID was never learned, or the opener was killed after
spawning) the member stays 'admitted' with no process, and recovery reads the project's Studio registry record
instead (native_work_pool_recovery.studio_launch_evidence): it refuses while the start's server runs, found by its
exact command, and when the record is missing (fail closed). Recovery is driven as an operator would after the
opener exited (``recover_with_table``: the member's supervisor is a dead TEST identity).
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_mix as mix
import native_work_pool_recovery as pool_recovery
import native_work_recovery as recovery
from native_render_processes import process_table
from native_work_pool_policy import STUDIO_CLASS
from native_work_workload import unrecorded
from studio import managed_preview_launch as launching
from _managed_preview_fixture import ManagedPreviewFixture
from _native_pool_fixture import qualify_fixture_host
from test_managed_preview_studio_class import DEAD, SLOTS, PoolHelpers

ROOT_ONLY = '1 0 1 Wed Sep  9 01:00:00 2026\n'            # the TEST process table: init only
SURVIVOR = dict(pid=25001, pgid=24999, started='Wed Sep  9 11:00:01 2026', command='TEST headless browser')


class StudioRecoveryTests(PoolHelpers, ManagedPreviewFixture, unittest.TestCase):
    """Which quarantined Studio members recovery by nonce releases, and on what evidence."""

    def setUp(self) -> None:
        """Manager fixture (private registry and pool namespace) plus a TEST record."""
        super().setUp()
        self.pool_root = self.root / 'registry'
        qualify_fixture_host(self, SLOTS)

    def quarantined(self, launch: object) -> dict:
        """Open draft 0 with ``launch`` as the preview launcher (it raises); return its quarantined member."""
        self.mocks[3].side_effect = launch
        with self.assertRaises(RuntimeError):
            self.open(0, wait_seconds=0)
        [member] = self.records(self.pool_root)
        self.assertEqual(member['class'], STUDIO_CLASS)
        return member

    def recover_with_table(self, nonce: str, table_text: str = ROOT_ONLY) -> dict:
        """Recover as an operator would once the opener exited; the process table is the TEST one given."""
        path = self.pool_root / 'pool-v1' / f'm-{nonce}.json'
        path.write_text(json.dumps(dict(json.loads(path.read_text()), supervisor=DEAD, supervisorPid=DEAD['pid'])))
        with mock.patch.object(pool_recovery, 'process_snapshot', return_value=process_table(table_text)):
            return recovery.recover(nonce)

    def spawned_then_failed(self, cli: str, project: str, port: int, **options: object) -> None:
        """The launcher spawns the preview server, then fails without returning its PID (an unknown launch)."""
        self.launch(cli, project, port, **options)
        raise RuntimeError('TEST Studio start failed after spawning; its PID was never learned')

    def test_known_survivors_are_recorded_and_must_exit(self) -> None:
        """M1 (the reviewer's probes): the reaped root's group member is on the member; recovery waits for it."""
        def failed(_cli: str, _project: str, _port: int, **_options: object) -> None:
            """The root 24999 was reaped; its group member 25001 still runs."""
            self.identities[25001] = SURVIVOR
            error = RuntimeError('TEST Studio preview exited before readiness')
            error.preview_pid = 24999
            raise error
        member = self.quarantined(failed)
        self.assertEqual((member['phase'], [row['pid'] for row in member['processes']]), ('launching', [25001]))
        alive = ROOT_ONLY + '25001 1 24999 Wed Sep  9 11:00:01 2026\n'
        with self.assertRaisesRegex(work.NativeWorkBusy, 'Recorded native children are still alive'):
            self.recover_with_table(member['nonce'], alive)
        self.identities.pop(25001)
        self.assertEqual(self.recover_with_table(member['nonce'])['memberClass'], STUDIO_CLASS)
        self.assertEqual(self.records(self.pool_root), [])

    def test_an_unknown_launch_is_found_by_its_command(self) -> None:
        """b': the launched PID was never learned; the server is found by its exact command until it exits."""
        member = self.quarantined(self.spawned_then_failed)
        self.assertEqual((member['phase'], member['processes']), ('admitted', []))
        [server] = list(self.identities)
        with self.assertRaisesRegex(work.NativeWorkBusy, rf'its start still runs \(pids \[{server}\]\)'):
            self.recover_with_table(member['nonce'])
        self.identities.pop(server)
        result = self.recover_with_table(member['nonce'])
        proof = json.loads((self.pool_root / 'pool-v1' / f'recovery-{member["nonce"]}.json').read_text())
        self.assertEqual((result['memberClass'], proof['studioLaunch']['registryState']), (STUDIO_CLASS, 'launching'))

    def test_an_opener_killed_after_spawning_is_found_by_its_command(self) -> None:
        """b': the opener dies before settling (E-CRASH-5): only its pre-spawn 'launching' record and the server
        remain; recovery refuses while that server runs."""
        with mock.patch.object(launching, '_record_failure'):   # killed before any settlement was written
            member = self.quarantined(self.spawned_then_failed)
        self.assertEqual(json.loads(self.record(0).read_text())['state'], 'launching')
        [server] = list(self.identities)
        with self.assertRaisesRegex(work.NativeWorkBusy, rf'its start still runs \(pids \[{server}\]\)'):
            self.recover_with_table(member['nonce'])
        self.identities.pop(server)
        self.assertEqual(self.recover_with_table(member['nonce'])['memberClass'], STUDIO_CLASS)

    def test_a_member_whose_project_has_no_registry_record_is_refused(self) -> None:
        """b': fail closed. A Studio member with no registry record for its project proves no start ended."""
        member = self.quarantined(self.spawned_then_failed)
        self.record(0).unlink()
        with self.assertRaisesRegex(work.NativeWorkBusy, 'has no Studio registry record for .* nothing proves its '
                                                         'start ended; recovery refused'):
            self.recover_with_table(member['nonce'])
        self.assertEqual(len(self.records(self.pool_root)), 1)

    def test_a_member_whose_registry_record_is_unreadable_is_refused(self) -> None:
        """b' (X247): fail closed. A torn or unparseable record proves nothing about the start; nothing is released."""
        member = self.quarantined(self.spawned_then_failed)
        for torn in (b'{"schemaVersion": 2, "state": "launch', b'[]'):
            self.record(0).write_bytes(torn)
            with self.subTest(record=torn), self.assertRaisesRegex(
                    work.NativeWorkBusy, 'its Studio registry record cannot be read .*; recovery refused'):
                self.recover_with_table(member['nonce'])
        self.assertEqual(len(self.records(self.pool_root)), 1)

    def test_a_group_that_empties_within_the_settle_bound_releases_the_slot(self) -> None:
        """m1: the reaped root's group member, still listed at the first read and gone at the next, is no
        survivor: the start's cleanup is verified and its slot released."""
        def reaped(_cli: str, _project: str, _port: int, **_options: object) -> None:
            """studio_server reaped its own child 24998 after a readiness failure."""
            error = RuntimeError('TEST Studio preview exited before readiness')
            error.preview_pid = 24998
            raise error
        self.mocks[3].side_effect = reaped
        group = [[dict(pid=25002, pgid=24998, started='Wed Sep  9 11:00:02 2026')], []]
        with mock.patch.object(launching, 'group_survivors', side_effect=group), self.assertRaises(RuntimeError):
            self.open(0, wait_seconds=0)
        self.assertEqual(json.loads(self.record(0).read_text())['state'], 'stopped')
        self.assertEqual(self.records(self.pool_root), [])

    def test_a_studio_open_describes_no_workload(self) -> None:
        """m5: a Studio request is never described; its ticket's workload is the unrecorded 'studio' row."""
        with mock.patch.object(mix.workloads, 'describe', side_effect=AssertionError('TEST describe called')) as seen:
            self.open(0, wait_seconds=0)
        seen.assert_not_called()
        request = pool.PoolRequest(STUDIO_CLASS, str(self.projects[1]), declares_launch=True)
        self.addCleanup(request.withdraw)
        mix.describe(request, needs_engine=True)
        self.assertEqual(request.workload, unrecorded(STUDIO_CLASS))


if __name__ == '__main__':
    unittest.main()
