"""Unfinished Studio launches and runtime identity across checkouts.

A killed opener leaves its project's registry record 'launching' and may leave its server running
unregistered. The fence lasts only while a process of that launch runs: open replaces this
project's own survivor after admission, stop stops it, and every command closes a fence whose
processes are gone. Stock servers and other ports are never taken for a survivor.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
from _managed_preview_fixture import ManagedPreviewFixture
from graphics.render_tools import resolve_tools
from native_render_resources import GIB, ProcessRequest, parse_snapshot
from studio import managed_preview as managed
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio.studio_server import ServerRecord, StudioServerError
from test_native_render_resources import raw_sample

ORPHAN = Path(__file__).resolve().parent / 'fixtures/studio_orphan.py'


class InterruptedLaunchTests(ManagedPreviewFixture, unittest.TestCase):
    """The opener dies between its 'launching' record and readiness; its server keeps running."""

    def interrupted(self, index: int = 0) -> int:
        """Kill the opener mid-startup (no handler runs); return its still-running server's PID."""
        def killed(cli: str, project: str, port: int, **options: object) -> None:
            self.launch(cli, project, port, **options)
            raise KeyboardInterrupt('TEST opener killed while waiting for readiness')
        self.mocks[3].side_effect = killed
        with mock.patch.object(managed, '_settle_failed_launch'), self.assertRaises(KeyboardInterrupt):
            self.open(index)
        self.mocks[3].side_effect = self.launch
        self.assertEqual(json.loads(self.record(index).read_text())['state'], 'launching')
        return self.next_pid

    def listed(self) -> dict:
        """Every managed record by project, as ``list`` reports it."""
        return {row['preview']['project']: row['preview'] for row in managed.list_previews()}

    def test_open_replaces_its_own_orphan_and_leaves_other_projects_alone(self) -> None:
        orphan = self.interrupted()
        other = self.open(1)
        fence = self.listed()[str(self.projects[0])]
        self.assertEqual((fence['state'], [row['pid'] for row in fence['processes']]), ('launching', [orphan]))
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            current = self.open()
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {orphan})
        self.assertNotIn(orphan, self.identities)
        self.assertIn(current.pid, self.identities)
        self.assertIn(other.pid, self.identities)
        self.assertEqual(json.loads(self.record(0).read_text())['state'], 'running')

    def test_a_launch_whose_server_already_exited_closes_without_any_signal(self) -> None:
        self.identities.pop(self.interrupted())
        with mock.patch.object(state.os, 'kill') as stop:
            self.assertEqual(self.listed()[str(self.projects[0])]['state'], 'stopped')
            self.assertIn(self.open().pid, self.identities)
        stop.assert_not_called()

    def test_stop_discharges_the_fence_and_frees_its_view_slot(self) -> None:
        orphan = self.interrupted()
        opened = [self.open(index) for index in range(1, registry.MAX_MANAGED_PREVIEWS)]
        with mock.patch.object(state.os, 'kill') as stop, \
                self.assertRaisesRegex(StudioServerError, r'limit of 6 views reached.*draft-0 \[launching\]'):
            self.open(registry.MAX_MANAGED_PREVIEWS)
        stop.assert_not_called()
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            managed.stop_preview(str(self.projects[0]))
        self.assertNotIn(orphan, self.identities)
        self.assertEqual(json.loads(self.record(0).read_text())['cleanup']['verified'], True)
        self.assertIn(self.open(registry.MAX_MANAGED_PREVIEWS).pid, self.identities)
        self.assertTrue(all(record.pid in self.identities for record in opened))

    def test_only_a_sniper_server_on_the_launch_port_is_a_survivor(self) -> None:
        """A stock server of the same project, or ours on another port, is never signalled."""
        project = str(self.projects[0])
        stock = self.launch('/stock/hyperframes/dist/cli.js', project, 3990, open_browser=False).pid
        elsewhere = self.launch(self.cli, project, 3999, open_browser=False).pid
        orphan = self.interrupted()
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            managed.stop_preview(project)
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {orphan})
        self.assertIn(stock, self.identities)
        self.assertIn(elsewhere, self.identities)

    def test_only_the_recorded_cli_is_the_launch_server(self) -> None:
        """Another checkout's server of this project and port is not this launch's survivor."""
        other = str(self.checkout_runtime('checkout-b', 'TEST-identity-a') / 'dist/cli.js')
        foreign = self.launch(other, str(self.projects[0]), 3990, open_browser=False).pid
        orphan = self.interrupted()
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            managed.stop_preview(str(self.projects[0]))
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {orphan})
        self.assertIn(foreign, self.identities)

    def test_a_record_without_port_or_cli_is_never_matched_by_command(self) -> None:
        """Earlier code's 'launching' records name no port: only retained identities count."""
        project = str(self.projects[0])
        running = self.launch(self.cli, project, 3990, open_browser=False).pid
        with registry.transaction(registry.monotonic_until(1)) as reg:
            registry.write_entry(reg, dict(schemaVersion=2, state='launching', project=project))
        with mock.patch.object(state.os, 'kill') as stop:
            managed.stop_preview(project)
        stop.assert_not_called()
        self.assertIn(running, self.identities)
        self.assertEqual(json.loads(self.record(0).read_text())['state'], 'stopped')

    def test_an_unreadable_process_table_refuses_instead_of_settling(self) -> None:
        """A row the scan cannot read could be the survivor: nothing is closed or signalled."""
        self.interrupted()
        with mock.patch.object(state, 'read_command_table', side_effect=state.StudioServerError('TEST unreadable')), \
                self.assertRaisesRegex(StudioServerError, 'TEST unreadable'):
            managed.stop_preview(str(self.projects[0]))
        self.assertEqual(json.loads(self.record(0).read_text())['state'], 'launching')

    def test_a_survivor_that_will_not_exit_keeps_only_its_project_fenced(self) -> None:
        orphan = self.interrupted()
        with mock.patch.object(state, 'terminate_tree', return_value=dict(verified=False, survivors=[], signals=[])), \
                self.assertRaisesRegex(StudioServerError, rf'did not exit \(pids \[{orphan}\]\)'):
            self.open()
        fence = json.loads(self.record(0).read_text())
        self.assertEqual((fence['state'], [row['pid'] for row in fence['processes']]), ('launching', [orphan]))
        self.assertIn(self.open(1).pid, self.identities)


class ProcessTableParsingTests(unittest.TestCase):
    """The scan reads every row in the C locale and refuses a row it cannot read."""

    def test_malformed_row_fails_closed_and_empty_commands_parse(self) -> None:
        with mock.patch.object(state, '_ps', return_value=(0, '  7   7 Sun Sep 27 14:06:07 2026\nTEST garbage\n', '')), \
                self.assertRaisesRegex(StudioServerError, 'Cannot read the process table'):
            state.read_command_table()
        french = '  7   7 dim. 27 sept. 14:06:07 2026 node /TEST/cli.js preview /TEST --port 3990\n'
        with mock.patch.object(state, '_ps', return_value=(0, french, '')), \
                self.assertRaisesRegex(StudioServerError, 'Cannot read the process table'):
            state.read_command_table()  # another locale's date is never read as a shorter C date
        with mock.patch.object(state, '_ps', return_value=(0, '  7   7 Sun Sep 27 14:06:07 2026   \n', '')):
            self.assertEqual(state.read_command_table(), [dict(pid=7, pgid=7, started='Sun Sep 27 14:06:07 2026',
                                                               command='')])

    def test_a_process_that_is_not_ours_to_signal_is_not_signalled(self) -> None:
        row = dict(pid=7, pgid=7, started='TEST')
        with mock.patch.object(state, 'identity_matches', return_value=True), \
                mock.patch.object(state, 'read_tree_table', return_value={}), \
                mock.patch.object(state.os, 'kill', side_effect=PermissionError('TEST another user')):
            self.assertFalse(state._signal_process(row, signal.SIGTERM))


class CrossCheckoutRuntimeTests(ManagedPreviewFixture, unittest.TestCase):
    """Checkouts build their runtime at different paths; the content identity decides reuse."""

    def test_same_runtime_content_from_another_checkout_is_reused(self) -> None:
        first = self.open()
        self.mocks[6].return_value = self.checkout_runtime('checkout-b', 'TEST-identity-a')
        with mock.patch.object(state.os, 'kill') as stop:
            self.assertEqual(self.open(), first)
            self.mocks[6].return_value = self.runtime
            self.assertEqual(self.open(), first)
        stop.assert_not_called()
        self.assertEqual(self.mocks[3].call_count, 1)

    def test_different_runtime_content_is_replaced(self) -> None:
        first = self.open()
        upgraded = self.checkout_runtime('checkout-b', 'TEST-identity-b')
        self.mocks[6].return_value = upgraded
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            current = self.open()
        self.assertNotIn(first.pid, self.identities)
        self.assertEqual(self.mocks[3].call_args.args[0], str(upgraded / 'dist/cli.js'))
        self.assertIn(current.pid, self.identities)


class KilledOpenerProcessTests(unittest.TestCase):
    """Real processes and the real ps scan: the opener is SIGKILLed while its server starts."""

    FOLDER = 'ascii'  # the checkout and project live below this folder

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve() / self.FOLDER
        self.root.mkdir()
        self.project = self.root / 'clip'
        self.project.mkdir()
        (self.project / 'index.html').write_text('<html>TEST</html>')
        self.node = resolve_tools()['node']  # the installed Node runs TEST scripts that only sleep
        self.runtime = self.root / 'templates/motion/.sniper-native-runtime/TEST-identity/hyperframes'
        self.cli = self.server_code(self.runtime / 'dist/cli.js')
        self.enterContext(mock.patch.object(work, 'state_root', return_value=self.root / 'registry'))
        self.enterContext(mock.patch.object(managed, 'read_snapshot', return_value=parse_snapshot(
            raw_sample(), ProcessRequest(), 40 * GIB)))
        self.enterContext(mock.patch.object(managed, 'install_runtime', return_value=self.runtime))

    def server_code(self, cli: Path) -> str:
        """The TEST cli.js a server look-alike runs: a sleep, never HyperFrames."""
        cli.parent.mkdir(parents=True)
        cli.write_text('setTimeout(() => {}, 120000);\n')
        return str(cli)

    def watch(self, pid: int, cli: str) -> int:
        """Kill a leftover look-alike at the end, only while it is still exactly ours."""
        def cleanup() -> None:
            identity = state.process_identity(pid)
            if identity and cli in identity['command']:
                os.kill(pid, signal.SIGKILL)
        self.addCleanup(cleanup)
        return pid

    def spawn(self, cli: str, port: int) -> int:
        """A reparented server look-alike, as a killed opener leaves it."""
        output = subprocess.run([sys.executable, '-B', str(ORPHAN), 'spawn', self.node, cli, str(self.project),
                                 str(port)], capture_output=True, text=True, check=True, timeout=30)
        return self.watch(int(output.stdout), cli)

    def kill_opener(self) -> int:
        """Run the real opener in a child, SIGKILL it inside the readiness wait; return its server."""
        child = subprocess.Popen([sys.executable, '-B', str(ORPHAN), 'opener', self.node, str(self.root / 'registry'),
                                  str(self.runtime), str(self.project)], stdout=subprocess.PIPE, text=True)
        orphan = self.watch(int(child.stdout.readline().split()[1]), self.cli)
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
        child.stdout.close()
        return orphan

    def entry(self) -> dict:
        """The project's registry record."""
        with registry.transaction(registry.monotonic_until(5)) as reg:
            return registry.read_entry(reg, str(self.project))

    def launch(self, cli: str, project: str, port: int, **_options: object) -> ServerRecord:
        """A new look-alike server, as the launcher would start it."""
        return ServerRecord(port, self.spawn(cli, port), f'http://localhost:{port}', 'TEST')

    def test_stop_finds_the_orphan_by_its_exact_command_and_stops_only_it(self) -> None:
        stock = self.spawn(self.server_code(self.root / 'stock/node_modules/hyperframes/dist/cli.js'), 3990)
        orphan = self.kill_opener()
        self.assertEqual({key: self.entry()[key] for key in ('state', 'port')}, {'state': 'launching', 'port': 3990})
        managed.stop_preview(str(self.project), 5)
        stopped = self.entry()
        self.assertEqual((stopped['state'], stopped['cleanup']['verified']), ('stopped', True))
        self.assertIsNone(state.process_identity(orphan))
        self.assertIsNotNone(state.process_identity(stock))

    def test_the_scan_reads_the_table_in_any_caller_locale_and_any_argument_bytes(self) -> None:
        """A French caller locale and a host process with non-UTF-8 arguments change nothing."""
        stranger = subprocess.Popen([self.node, '-e', 'setTimeout(() => {}, 120000)', b'TEST-\xff\xfe',
                                     'TEST-\u2028-\u0085-\x0b-row  1 1 Sun Sep 27 14:06:07 2026 forged'],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(stranger.wait)
        self.addCleanup(stranger.kill)
        orphan = self.kill_opener()
        french = {'LANG': 'fr_FR.UTF-8', 'LC_ALL': 'fr_FR.UTF-8', 'LC_TIME': 'fr_FR.UTF-8'}
        with mock.patch.dict(os.environ, french):
            self.assertEqual(managed.list_previews()[0]['preview']['state'], 'launching')
            managed.stop_preview(str(self.project), 5)
        self.assertEqual((self.entry()['state'], self.entry()['cleanup']['verified']), ('stopped', True))
        self.assertIsNone(state.process_identity(orphan))
        self.assertIsNone(stranger.poll())

    def test_open_replaces_the_orphan_with_a_registered_server(self) -> None:
        orphan = self.kill_opener()
        with mock.patch.object(managed, 'launch_preview', side_effect=self.launch):
            record = managed.open_preview(str(self.project), 3990, None, 5)
        self.assertIsNone(state.process_identity(orphan))
        self.assertEqual((self.entry()['state'], self.entry()['identity']['pid']), ('running', record.pid))
        managed.stop_preview(str(self.project), 5)
        deadline = time.monotonic() + 5
        while state.process_identity(record.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNone(state.process_identity(record.pid))


class NonAsciiPathProcessTests(KilledOpenerProcessTests):
    """The same real-process checks with a non-ASCII, spaced checkout and project path."""

    FOLDER = 'Développement été'


class LaunchDischargeTests(ManagedPreviewFixture, unittest.TestCase):
    """A failed launch's own PID running another command is never taken for 'exited'."""

    def test_unexpected_command_on_the_launched_pid_stays_fenced(self) -> None:
        def failed(_cli: str, project: str, port: int, **options: object) -> None:
            record = self.launch('/TEST/unexpected/cli.js', project, port, **options)
            error = StudioServerError('TEST readiness failed')
            error.preview_pid = record.pid
            raise error
        self.mocks[3].side_effect = failed
        with mock.patch.object(state.os, 'kill') as stop, self.assertRaisesRegex(StudioServerError, 'readiness'):
            self.open()
        stop.assert_not_called()
        fence = json.loads(self.record(0).read_text())
        self.assertEqual((fence['state'], fence['cleanup']['reason']),
                         ('launching', 'launched process runs an unexpected command'))
        self.assertEqual([row['pid'] for row in fence['processes']], [self.next_pid])


if __name__ == '__main__':
    unittest.main()
