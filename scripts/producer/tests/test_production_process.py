"""Process supervision (units A3/A4): the exact supervised claim, the export watchdog and its process group.

TEST child processes stand in for the exporter: they run the real ``supervised_claim`` and are
stopped only by the watchdog this test runs, and every process a test waits on is one it started.
Deadlines are short synthetic allocations; the batch authority is a private temporary root. No
render, host or real exporter runs here. Settlement and the exporter entry are in
``test_production_settle.py``.
"""
from __future__ import annotations

import contextlib
import io
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

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _dispatch_fixture import PRODUCER
from headless.process_runner import LEDGER_ENV
from studio import native_budget_binding as binding
from studio.native_budget_clock import allocation, allocation_remaining, start_anchor
from studio.native_budget_store import BudgetAuthorityError
from studio.production import process, process_group, process_output, process_watch
from studio.production.process import ExportLaunch, TaskClaim
from studio.production.process_watch import DEADLINE, INTERRUPTED, ExportWatch, OutputRelay

CLAIMANT = ('import json, sys; sys.path[:0] = [{producer!r}]\n'
            'from studio.production import process\n'
            'try:\n'
            '    found = process.supervised_claim()\n'
            '    print(json.dumps({{"result": "none" if found is None else "ok",\n'
            '                      "task": found.task.record() if found and found.task else None}}))\n'
            'except process.SupervisionRefused as error:\n'
            '    print(json.dumps({{"result": "refused", "reason": str(error)}}))\n').format(producer=str(PRODUCER))
SLEEPER = 'import time\ntime.sleep(60)\n'
# Each helper writes the pid of the process it leaves behind to argv[1].
STUBBORN = ('import signal, subprocess, sys, time\n'
            'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            'helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            'open(sys.argv[1], "w").write(str(helper.pid))\n'
            'time.sleep(60)\n')
EXITS_LEAVING_A_GROUP_MEMBER = ('import subprocess, sys\n'
                                'helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
                                'open(sys.argv[1], "w").write(str(helper.pid))\n')
OWNER_WITH_A_RECORDED_SESSION = (f'import signal, subprocess, sys, time; sys.path[:0] = [{str(PRODUCER)!r}]\n'
                                 'from headless.process_runner import note_owned_session\n'
                                 'render = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],\n'
                                 '                          start_new_session=True)\n'
                                 'note_owned_session(render, (sys.executable,))\n'
                                 'open(sys.argv[1], "w").write(str(render.pid))\n'
                                 'signal.signal(signal.SIGTERM, signal.SIG_IGN)   # cleanup outlasts the grace\n'
                                 'time.sleep(60)\n')


def private_directory(test: unittest.TestCase) -> Path:
    """A canonical private directory removed after the test."""
    directory = Path(tempfile.mkdtemp(prefix='sniper-process-')).resolve()
    test.addCleanup(lambda: subprocess.run(['rm', '-rf', str(directory)], check=False))
    return directory


def gone(pid: int) -> bool:
    """Whether no process has this pid (a reaped or never-existing process; a zombie counts as gone)."""
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return state == '' or state.startswith('Z')


def wait_gone(pid: int, seconds: float) -> bool:
    """Poll until this pid is gone or the bound passes."""
    until = time.monotonic() + seconds
    while not gone(pid) and time.monotonic() < until:
        time.sleep(0.05)
    return gone(pid)


def read_pid(path: Path, seconds: float = 20.0) -> int:
    """The pid a TEST child wrote."""
    until = time.monotonic() + seconds
    while not (path.is_file() and path.read_text().strip()) and time.monotonic() < until:
        time.sleep(0.05)
    return int(path.read_text())


def kill_if_alive(pid: int) -> None:
    """Cleanup for a process this test started (never another)."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)


class SupervisedClaimTests(unittest.TestCase):
    """The internal exporter entry needs this exact claim: its live parent, its arguments, used once."""

    def setUp(self) -> None:
        self.directory = private_directory(self)
        self.arguments = ('/TEST/project', '/TEST/out', '--review-draft')
        self.task = TaskClaim('batch-auth', 'draft-a', 1, 'a' * 32, 'e' * 64)
        self.claim = process.write_claim(self.directory, ExportLaunch(self.arguments, Path('/TEST/project'), self.task))

    def claimant(self, arguments: tuple = (), claim: Path | None = None, own_group: bool = True) -> dict:
        environment = {**os.environ, process.CLAIM_ENV: str(claim or self.claim)}
        result = subprocess.run([sys.executable, '-B', '-c', CLAIMANT, *(arguments or self.arguments)],
                                env=environment, capture_output=True, text=True, timeout=60,
                                start_new_session=own_group)
        return json.loads(result.stdout)

    def rewrite(self, change: object) -> None:
        value = json.loads(self.claim.read_text())
        change(value)
        self.claim.write_text(json.dumps(value))

    def test_the_exact_child_acknowledges_once(self) -> None:
        self.assertEqual(self.claimant(), {'result': 'ok', 'task': self.task.record()})
        replay = self.claimant()
        self.assertEqual(replay['result'], 'refused')
        self.assertIn('already acknowledged', replay['reason'])

    def test_other_arguments_are_refused(self) -> None:
        refused = self.claimant(('/TEST/project', '/TEST/other-out', '--review-draft'))
        self.assertIn('other exporter arguments', refused['reason'])

    def test_a_watchdog_that_is_not_the_live_parent_is_refused(self) -> None:
        self.rewrite(lambda value: value['watchdog'].update(started='Thu Jan  1 00:00:00 1970'))  # a reused PID
        self.assertIn('live watchdog', self.claimant()['reason'])
        self.rewrite(lambda value: value['watchdog'].update(pid=1, pgid=1))
        self.assertIn('live watchdog', self.claimant()['reason'])

    def test_a_child_in_its_parents_group_is_refused(self) -> None:
        # Its orphan stop SIGKILLs its own group, so it must lead one (the watchdog starts it in its own session).
        self.assertIn('leads its own process group', self.claimant(own_group=False)['reason'])
        self.assertEqual(self.claimant()['result'], 'ok')           # the refused attempt consumed nothing

    def test_the_claim_is_not_authentication(self) -> None:
        # Minor 9 / probe p8, documented in process.py: any same-user parent that writes a claim naming itself
        # and starts the exporter in its own session is accepted as its watchdog. The claim rules out reuse,
        # a dead supervisor and a second child, not a forger.
        forged = process.write_claim(private_directory(self), ExportLaunch(self.arguments, None))
        self.assertEqual(self.claimant(claim=forged)['result'], 'ok')
        self.assertIn('not authentication', process.__doc__)

    def test_a_task_claim_without_its_request_hash_is_refused(self) -> None:
        self.rewrite(lambda value: value['task'].pop('requestSha256'))
        self.assertIn('malformed task claim', self.claimant()['reason'])

    def test_a_variable_naming_no_private_claim_is_refused(self) -> None:
        loose = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: subprocess.run(['rm', '-rf', str(loose)], check=False))
        os.chmod(loose, 0o755)
        (loose / process.CLAIM).write_text(self.claim.read_text())
        self.assertIn('unreadable', self.claimant(claim=loose / process.CLAIM)['reason'])
        self.assertIn('does not name', self.claimant(claim=self.directory / 'other.json')['reason'])

    def orphan(self, child_code: str) -> tuple[int, Path]:
        """Start a TEST watchdog that starts ``child_code`` on a real claim; return (child pid, claim directory)."""
        watchdog_code = (f'import os, subprocess, sys, time; sys.path[:0] = [{str(PRODUCER)!r}]\n'
                         'from pathlib import Path\n'
                         'from studio.production import process\n'
                         'claim = process.write_claim(Path(sys.argv[1]), process.ExportLaunch(("a", "b"), Path("/TEST")))\n'
                         f'child = subprocess.Popen([sys.executable, "-c", {child_code!r}, "a", "b"],\n'
                         '                         env={**os.environ, process.CLAIM_ENV: str(claim)},\n'
                         '                         start_new_session=True)\n'
                         'print(child.pid, flush=True)\n'
                         'time.sleep(60)\n')
        directory = private_directory(self)
        watchdog = subprocess.Popen([sys.executable, '-c', watchdog_code, str(directory)], stdout=subprocess.PIPE,
                                    text=True)
        self.addCleanup(watchdog.stdout.close)
        child = int(watchdog.stdout.readline())
        self.addCleanup(kill_if_alive, child)
        until = time.monotonic() + 30
        while not (directory / process.ACKNOWLEDGED).exists() and time.monotonic() < until:
            time.sleep(0.05)
        self.assertTrue((directory / process.ACKNOWLEDGED).exists())
        watchdog.kill()                                           # the watchdog this test started dies
        watchdog.wait()
        return child, directory

    def test_an_export_whose_watchdog_dies_stops_itself(self) -> None:
        child, _ = self.orphan(f'import sys, time; sys.path[:0] = [{str(PRODUCER)!r}]\n'
                               'from studio.production import process\n'
                               'process.POLL_SECONDS = 0.1\n'
                               'process.supervised_claim()\n'
                               'time.sleep(60)\n')
        self.assertTrue(wait_gone(child, 10), 'the export outlived its watchdog')

    def test_an_orphan_whose_cleanup_outlasts_the_grace_kills_its_own_group(self) -> None:
        # Probe p14 (minor 10): the canary's timeout SIGKILLs the watchdog; the orphaned child's cleanup
        # would take 30 s, but after the grace it SIGKILLs its own process group.
        child, directory = self.orphan(f'import sys, time; sys.path[:0] = [{str(PRODUCER)!r}]\n'
                                       'from studio.production import process\n'
                                       'process.POLL_SECONDS, process.STOP_GRACE_SECONDS = 0.1, 1.0\n'
                                       'process.supervised_claim()\n'
                                       'with process.interrupt_on_termination():\n'
                                       '    try:\n'
                                       '        time.sleep(60)\n'
                                       '    except KeyboardInterrupt:\n'
                                       '        time.sleep(30)\n')
        began = time.monotonic()
        self.assertTrue(wait_gone(child, 10), 'the orphaned export outlived its grace')
        self.assertLess(time.monotonic() - began, 10)

    def test_without_a_claim_the_entry_supervises_instead(self) -> None:
        result = subprocess.run([sys.executable, '-B', '-c', CLAIMANT], capture_output=True, text=True, timeout=60,
                                env={key: value for key, value in os.environ.items() if key != process.CLAIM_ENV})
        self.assertEqual(json.loads(result.stdout), {'result': 'none', 'task': None})


class WatchdogTests(unittest.TestCase):
    """The watchdog stops its child at the deadline, the launch grant or its own stop, then ends its group."""

    def setUp(self) -> None:
        self.directory = private_directory(self)
        self.enterContext(mock.patch.object(process, 'POLL_SECONDS', 0.1))
        self.enterContext(mock.patch.object(process, 'STOP_GRACE_SECONDS', 1.0))
        self.enterContext(mock.patch.object(process, 'REAP_SECONDS', 3.0))
        self.pidfile = self.directory / 'left-behind.pid'

    def watch(self, seconds: float = 3600.0) -> ExportWatch:
        deadline = allocation(start_anchor(), seconds, 0.0)
        return ExportWatch(None, self.directory, deadline, time.monotonic(), time.time())

    def child(self, code: str = SLEEPER) -> subprocess.Popen:
        environment = {**os.environ, LEDGER_ENV: str(self.directory / process.LEDGER)}
        child = subprocess.Popen([sys.executable, '-c', code, str(self.pidfile)], start_new_session=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        self.addCleanup(lambda: child.poll() is None and (child.kill() or child.wait()))
        return child

    def run_watch(self, child: subprocess.Popen, watch: ExportWatch, stops: object = None) -> tuple:
        """watch_child, then end the group and reap, as supervise_export does."""
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            relay = OutputRelay(child)
            reason = process_watch.watch_child(child, watch, stops or process._Stops(), relay)
            survivors = process_group.end_group(child, self.directory, watch.since)
            relay.drain()
        return reason, survivors

    def test_a_hung_setup_is_stopped_at_the_batch_deadline(self) -> None:
        watch, began = self.watch(0.5), time.monotonic()
        reason, survivors = self.run_watch(self.child(), watch)
        self.assertEqual((reason[0], survivors), (DEADLINE, []))
        self.assertLess(time.monotonic() - began, 5)

    def test_the_published_launch_grant_tightens_the_deadline(self) -> None:
        watch = self.watch()
        from cut_preview_io import write_new
        write_new(self.directory / process.GRANT, allocation(start_anchor(), -30.0, 45.0))
        self.assertEqual(self.run_watch(self.child(), watch)[0][1], 'the export ran past its launch grant')

    def test_a_stubborn_child_and_its_group_are_killed_after_the_grace(self) -> None:
        stops = process._Stops()
        stops.reason = 'received SIGTERM'
        watch = self.watch()
        child = self.child(STUBBORN)
        helper = read_pid(self.pidfile)
        self.addCleanup(kill_if_alive, helper)
        reason, survivors = self.run_watch(child, watch, stops)
        self.assertEqual((reason[0], survivors, child.returncode), (INTERRUPTED, [], -signal.SIGKILL))
        self.assertTrue(wait_gone(helper, 5), 'the child\'s group survived the watchdog')

    def test_a_normal_exit_still_ends_the_childs_group(self) -> None:
        # Probe p3 (major 3): the child exits 0 leaving a same-group helper; waitid(WNOWAIT) keeps the
        # group id reserved, the watchdog SIGKILLs the group, then reaps.
        watch = self.watch()
        child = self.child(EXITS_LEAVING_A_GROUP_MEMBER)
        helper = read_pid(self.pidfile)
        self.addCleanup(kill_if_alive, helper)
        reason, survivors = self.run_watch(child, watch)
        self.assertEqual((reason, survivors, child.returncode), (None, [], 0))
        self.assertTrue(wait_gone(helper, 5), 'a same-group helper outlived a normal exit')

    def test_an_owners_recorded_own_session_is_ended_too(self) -> None:
        # Probe p10 (major 4): an owner started a render in its own session (as native_run does) and recorded
        # it in the ledger; its cleanup outlasts the grace. The watchdog ends that session as well.
        stops = process._Stops()
        stops.reason = 'received SIGTERM'
        watch = self.watch()
        child = self.child(OWNER_WITH_A_RECORDED_SESSION)
        render = read_pid(self.pidfile)
        self.addCleanup(kill_if_alive, render)
        group = subprocess.run(['ps', '-o', 'pgid=', '-p', str(render)], capture_output=True, text=True).stdout
        self.assertEqual(int(group), render)                          # its own session, outside the child's group
        reason, survivors = self.run_watch(child, watch, stops)
        self.assertEqual((reason[0], survivors), (INTERRUPTED, []))
        self.assertTrue(wait_gone(render, 5), 'the recorded render session outlived the stop')

    def test_survivors_are_reported_as_exact_identities(self) -> None:
        child = self.child()
        watch = self.watch(0.3)
        survivor = {'type': 'process', 'pid': 99999, 'pgid': 99999, 'started': 'TEST'}
        with mock.patch.object(process_group, '_living', return_value=[survivor]), \
                mock.patch.object(process, 'REAP_SECONDS', 0.3):
            reason, survivors = self.run_watch(child, watch)
        self.assertEqual((reason[0], survivors), (DEADLINE, [survivor]))

    def test_the_relayed_output_is_bounded(self) -> None:
        child = self.child('import sys\nsys.stdout.write("x" * 50000)\nsys.stdout.flush()\n')
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(process_output, 'OUTPUT_LIMIT_BYTES', 1000), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            relay = OutputRelay(child)
            process_watch.watch_child(child, self.watch(), process._Stops(), relay)
            process_group.end_group(child, self.directory, time.time())
            relay.drain()
        self.assertEqual(len(out.getvalue()), 1000)
        self.assertIn('is not shown', err.getvalue())


class SuperviseExportTests(unittest.TestCase):
    """supervise_export: every export runs under a deadline; an unbound one is a declared one-output run."""

    def setUp(self) -> None:
        self.directory = private_directory(self)
        self.enterContext(mock.patch.object(process, 'POLL_SECONDS', 0.1))
        self.enterContext(mock.patch.object(process, 'STOP_GRACE_SECONDS', 1.0))
        self.enterContext(mock.patch.object(process, 'REAP_SECONDS', 3.0))

    def script(self, code: str) -> Path:
        path = self.directory / 'child.py'
        path.write_text(f'import sys; sys.path[:0] = [{str(PRODUCER)!r}]\n' + code)
        return path

    def supervise(self, launch: ExportLaunch) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = process_watch.supervise_export(launch)
        return code, out.getvalue()

    def test_the_watchdog_reserves_and_charges_nothing(self) -> None:
        script = self.script('from studio.production import process\n'
                             'raise SystemExit(7 if process.supervised_claim() else 1)\n')
        refuse = mock.Mock(side_effect=AssertionError('the watchdog must not reserve'))
        made = []
        real = tempfile.mkdtemp
        def record(*args: object, **kwargs: object) -> str:
            made.append(real(*args, **kwargs))
            return made[-1]
        with mock.patch.object(binding, 'reserve_launch', refuse), \
                mock.patch.object(binding, 'reserve_task_launch', refuse), \
                mock.patch.object(process_watch.tempfile, 'mkdtemp', side_effect=record):
            code, _ = self.supervise(ExportLaunch(('/TEST/p', '/TEST/o'), None, script=script))
        self.assertEqual(code, 7)                              # the child verified its exact claim, then exited 7
        refuse.assert_not_called()
        claims = [path for path in made if Path(path).name.startswith('sniper-export-')]
        self.assertEqual(len(claims), 1)
        self.assertFalse(Path(claims[0]).exists())             # the claim directory is removed afterwards

    def test_an_unbound_export_is_a_declared_one_output_run_with_a_grant(self) -> None:
        # Plausible 14: a standalone public export (or resume_final_qc) runs under a real deadline and grant.
        script = self.script('import json, os\nfrom pathlib import Path\nfrom studio.production import process\n'
                             'claim = process.supervised_claim()\n'
                             'print(json.dumps(json.loads((claim.directory / process.GRANT).read_text())))\n')
        code, out = self.supervise(ExportLaunch(('/TEST/p', '/TEST/o'), None, script=script))
        self.assertEqual(code, 0)
        grant = json.loads(out.strip().splitlines()[-1])
        self.assertGreater(allocation_remaining(grant), process_watch.ONE_OUTPUT_SECONDS - 60)
        self.assertLessEqual(allocation_remaining(grant), process_watch.ONE_OUTPUT_SECONDS)

    def test_an_unreadable_authority_refuses_the_export(self) -> None:
        # Plausible 18: the deadline fails closed; nothing starts.
        marker = self.directory / 'started'
        script = self.script(f'open({str(marker)!r}, "w").write("ran")\n')
        project = self.directory / 'project'
        project.mkdir()
        with mock.patch('studio.production.process_watch.owner_binding', side_effect=BudgetAuthorityError('TEST')):
            code, out = self.supervise(ExportLaunch(('/TEST/p', '/TEST/o'), project, script=script))
        self.assertEqual((code, json.loads(out)['status']), (3, 'refused-by-export-watchdog'))
        self.assertFalse(marker.exists())

    def test_another_formats_project_never_gets_a_short_deadline(self) -> None:
        # D2 seam (fail closed until D1/D2 are integrated): a Long is refused, never stopped at minute 40.
        marker = self.directory / 'started'
        script = self.script(f'open({str(marker)!r}, "w").write("ran")\n')
        project = self.directory / 'long-project'
        project.mkdir()
        (project / 'LONG-PROJECT.json').write_text('{}')
        code, out = self.supervise(ExportLaunch(('/TEST/p', '/TEST/o'), project))
        self.assertEqual((code, json.loads(out)['status']), (3, 'refused-by-export-watchdog'))
        self.assertIn('is not a native Short', json.loads(out)['reason'])
        self.assertFalse(marker.exists())

    def test_a_cold_setup_past_its_deadline_is_stopped_and_reported(self) -> None:
        script = self.script(SLEEPER)
        with mock.patch.object(process_watch, 'run_deadline', return_value=(allocation(start_anchor(), 0.5, 0.0),
                                                                            False)):
            code, out = self.supervise(ExportLaunch(('/TEST/p', '/TEST/o'), None, script=script))
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual((report['status'], report['category'], report['survivors']),
                         ('stopped-by-export-watchdog', DEADLINE, []))
        self.assertEqual(code, 128 + signal.SIGTERM)


class OperatorFileTests(unittest.TestCase):
    """Plausible 18: --tasks, --artifact and --confirmation never block on a FIFO or read a non-regular file."""

    def test_a_fifo_is_refused_at_once(self) -> None:
        from studio.production import handoff, inputs
        fifo = private_directory(self) / 'named-pipe.json'
        os.mkfifo(fifo)
        began = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'not a regular file'):
            inputs.read_file(fifo)
        with self.assertRaisesRegex(ValueError, 'not a regular file'):
            inputs.receipts([fifo])
        with self.assertRaisesRegex(handoff.HandoffEvidenceError, 'not a bounded regular file'):
            handoff.handoff_evidence(fifo)
        self.assertLess(time.monotonic() - began, 2)


if __name__ == '__main__':
    unittest.main()
