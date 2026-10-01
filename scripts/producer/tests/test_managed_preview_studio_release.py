"""A failed Studio start's slot is released only on proved cleanup (X97 ruling 3, X150, X165 G1).

The Studio manager, registry and pool run for real through ManagedPreviewFixture (inert TEST preview identities; no
process starts) on a TEST schema-1 record, as in test_managed_preview_studio_class. A failed start completes its
Studio slot only when managed_preview_launch.settle_failed_launch proves every process of the start gone, the root
and its own process group; otherwise the slot stays quarantined, and the registry keeps the project's 'launching'
fence with the survivors for ``stop``. Settling that fails or is interrupted proves nothing either.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest
from unittest import mock

from native_work_pool_policy import STUDIO_CLASS
from studio import managed_preview_launch as launching
from studio import managed_preview_state as state
from studio.studio_server import StudioServerError
from _managed_preview_fixture import ManagedPreviewFixture
from _native_pool_fixture import qualify_fixture_host
from test_managed_preview_studio_class import SLOTS, PoolHelpers


class StudioReleaseTests(PoolHelpers, ManagedPreviewFixture, unittest.TestCase):
    """Which failed starts release the Studio slot, and on what proof."""

    def setUp(self) -> None:
        """Manager fixture (private registry and pool namespace) plus a TEST record."""
        super().setUp()
        self.pool_root = self.root / 'registry'
        qualify_fixture_host(self, SLOTS)

    def studio_members(self) -> list[str]:
        """The class of every pool member record left behind."""
        return [row['class'] for row in self.records(self.pool_root)]

    def failing_launch(self, pid: int, group_member: int | None = None) -> None:
        """The launcher fails after spawning `pid` and reaps it; optionally a process of its group survives."""
        def failed(_cli: str, _project: str, _port: int, **_options: object) -> None:
            """studio_server's readiness failure once it reaped its own child (untagged: it spawned)."""
            if group_member is not None:  # e.g. a browser the preview started in its own session
                self.identities[group_member] = dict(pid=group_member, pgid=pid, started='Wed Sep  9 11:00:01 2026',
                                                     command='TEST headless browser --type=renderer')
            error = StudioServerError('TEST Studio preview exited before readiness')
            error.preview_pid = pid
            raise error
        self.mocks[3].side_effect = failed

    def test_a_spawned_start_that_failed_keeps_its_slot_only_while_cleanup_is_unverified(self) -> None:
        """X150: a started server that fails verification releases the slot once it is proved gone, not before."""
        self.mocks[3].side_effect = lambda _cli, project, port, **options: self.launch(
            '/stock/hyperframes/dist/cli.js', project, port, **options)  # it spawns, then fails verification
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal), \
                self.assertRaisesRegex(StudioServerError, 'does not use the qualified'):
            self.open(0, wait_seconds=0)
        self.assertEqual(self.records(self.pool_root), [])  # stopped by identity, cleanup verified: released
        with mock.patch.object(state, 'terminate_tree', side_effect=lambda value: dict(
                verified=False, survivors=state.live_owned(value), signals=[])), \
                self.assertRaisesRegex(StudioServerError, 'does not use the qualified'):
            self.open(1, wait_seconds=0)
        self.assertEqual([row['class'] for row in self.records(self.pool_root)], [STUDIO_CLASS])  # a survivor
        self.assertEqual(json.loads(self.record(1).read_text())['state'], 'launching')  # it fences its project

    def test_a_reaped_root_whose_group_still_runs_keeps_the_slot_and_the_fence(self) -> None:
        """X165 G1: the root is reaped but a process of its group runs: nothing is proved gone or released."""
        self.failing_launch(24999, group_member=25001)
        with self.assertRaisesRegex(StudioServerError, 'exited before readiness'):
            self.open(0, wait_seconds=0)
        entry = json.loads(self.record(0).read_text())
        self.assertEqual((entry['state'], entry['cleanup']['verified'], entry['cleanup']['reason']),
                         ('launching', False, 'a process of the failed start still runs'))
        self.assertEqual([row['pid'] for row in entry['processes']], [25001])  # recorded, so `stop` can discharge it
        self.assertEqual(self.studio_members(), [STUDIO_CLASS])

    def test_a_reaped_root_releases_the_slot_while_other_views_run(self) -> None:
        """Other projects' live processes are not the failed start's group: its proved cleanup releases the slot."""
        other = self.open(1, wait_seconds=0)  # a live view of another project, in its own group
        self.failing_launch(24996)
        with self.assertRaisesRegex(StudioServerError, 'exited before readiness'):
            self.open(0, wait_seconds=0)
        self.assertEqual(json.loads(self.record(0).read_text())['state'], 'stopped')
        self.assertIn(other.pid, self.identities)
        self.assertEqual(self.studio_members(), [])

    def test_an_interrupt_while_settling_keeps_the_slot(self) -> None:
        """X165 m-a: an interrupt inside settling leaves the cleanup unproved, so the slot stays quarantined."""
        self.failing_launch(24998)
        with mock.patch.object(state, 'discharge_launch', side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            self.open(0, wait_seconds=0)
        self.assertEqual(self.studio_members(), [STUDIO_CLASS])

    def test_a_failed_settle_write_keeps_the_slot(self) -> None:
        """X165 m-a: the cleanup is verified but its record cannot be written: the slot stays, both causes noted."""
        self.failing_launch(24997)
        real = launching.registry.write_entry

        def refuse_settle(reg: object, value: dict) -> None:
            """Refuse only the failed launch's settlement record."""
            if 'cleanup' in value:
                raise OSError('TEST registry write refused')
            real(reg, value)
        with mock.patch.object(launching.registry, 'write_entry', side_effect=refuse_settle), \
                self.assertRaisesRegex(StudioServerError, 'exited before readiness') as caught:
            self.open(0, wait_seconds=0)
        self.assertIn('Studio startup cleanup was not verified: TEST registry write refused',
                      caught.exception.__notes__)
        self.assertEqual(self.studio_members(), [STUDIO_CLASS])


if __name__ == '__main__':
    unittest.main()
