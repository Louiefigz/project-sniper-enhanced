"""Python child processes started by tests carry the live-state tripwire (tests/_child_live_state).

T0's in-process audit hook cannot follow a child; ``_live_state_children.arm`` arms every child it can: the
tripwire folder first on the inherited PYTHONPATH, the parent's refused prefixes as JSON, a reports directory and
PYTHONDONTWRITEBYTECODE. These tests prove that a refused child exits 97 and leaves a report that fails the parent
run even when the child swallows everything, that the tripwire changes no child's modules or path, that a missing
or malformed variable fails closed, that the child's matcher refuses what the parent's refuses, and that the test
process itself does not load the child module (p0-records E-001; reviews/CS1-REVIEW.md F1, F2, ST-5). C1FIX-REVIEW
B1/M3: a second thread is refused too (never written), install failures leave a report, and a background or late
child's report names the test that started it. Every probe of a live path is read-only and names a file that does
not exist; writes go only under decoy prefixes in this test's own folder; a child that is meant to be refused
reports into this test's own directory, never into the run's.
"""
from __future__ import annotations

import _live_state_isolation as isolation
import _live_state_children as children
import _live_state_paths as paths

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ENGINE_MODULES = ('native_work_lease', 'native_render_processes', 'headless', 'headless.durable_files')
# Measured (C1FIX-REVIEW n2): the armed venv child loads exactly these modules a plain child does not (chain()).
ARMED_EXTRA = ['__future__', 'fcntl', 'importlib', 'importlib._abc', 'importlib._bootstrap',
               'importlib._bootstrap_external', 'importlib.machinery', 'importlib.util']
PROBE = paths.LIVE_BUDGET_ROOT / 'p0-child-probe-does-not-exist'
SWALLOW = f'try:\n    open({str(PROBE)!r})\nexcept BaseException:\n    pass\nprint("survived")\n'
STATE = 'import json, sys\nprint(json.dumps([sorted(sys.modules), sys.path]))\n'
# A real isolated test run in a child: its one test starts a swallowing grandchild and expects it to fail.
NESTED_RUN = f'''import io, json, subprocess, sys, unittest
import _live_state_isolation


class ExpectsAFailingCli(unittest.TestCase):
    def test_cli_fails(self):
        done = subprocess.run([sys.executable, '-B', '-c', {SWALLOW!r}], capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)


stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExpectsAFailingCli))
print(json.dumps([len(result.errors), len(result.failures), stream.getvalue()]))
'''


# A real isolated run: test 1 starts a child refused 1 s later, while test 2 is running.
BACKGROUND_RUN = f'''import io, json, subprocess, sys, time, unittest
import _live_state_isolation


class BackgroundChild(unittest.TestCase):
    def test_1_starts_a_late_child(self):
        subprocess.Popen([sys.executable, '-B', '-c', "import time; time.sleep(1); open({str(PROBE)!r})"])

    def test_2_runs_while_it_is_refused(self):
        time.sleep(3)


stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.loadTestsFromTestCase(BackgroundChild))
print(json.dumps([len(result.errors), stream.getvalue()]))
'''
# A real isolated run whose child is refused only after the run and its process have ended.
LATE_RUN = f'''import subprocess, sys, unittest
import _live_state_isolation


class LateChild(unittest.TestCase):
    def test_starts_a_child_that_outlives_the_run(self):
        subprocess.Popen([sys.executable, '-B', '-c', "import time; time.sleep(3); open({str(PROBE)!r})"],
                         start_new_session=True)


unittest.TextTestRunner(stream=sys.stderr).run(unittest.defaultTestLoader.loadTestsFromTestCase(LateChild))
'''


def outside_stdlib(names: list[str]) -> list[str]:
    """Module names whose top-level package is not part of the standard library."""
    return sorted(name for name in names if name.partition('.')[0] not in sys.stdlib_module_names)


class ChildTripwireTests(unittest.TestCase):
    """Python children inherit a refusing audit hook through PYTHONPATH (tests/_child_live_state)."""

    def child(self, code: str, environ: dict | None = None) -> subprocess.CompletedProcess:
        """Run one Python child with this process's environment (which carries the armed variables) or ``environ``."""
        return subprocess.run([sys.executable, '-B', '-c', code], env=environ or dict(os.environ), capture_output=True,
                              text=True, timeout=120, check=False)

    def private_reports(self) -> tuple[dict, Path]:
        """This process's environment with a reports directory of this test's own."""
        directory = Path(tempfile.mkdtemp(prefix='p0-child-reports-')).resolve()
        self.addCleanup(shutil.rmtree, directory)
        return dict(os.environ, **{children.REPORTS: str(directory)}), directory

    def decoy(self) -> tuple[dict, Path, Path]:
        """Environment whose refused prefixes also hold a decoy folder of this test's own: (env, decoy, reports)."""
        environ, reports = self.private_reports()
        decoy = Path(tempfile.mkdtemp(prefix='p0-decoy-')).resolve()
        self.addCleanup(shutil.rmtree, decoy)
        config = json.loads(environ[children.CONFIG])
        config['refused'] = sorted({*config['refused'], paths.canonical(str(decoy))})
        return dict(environ, **{children.CONFIG: json.dumps(config)}), decoy, reports

    def test_children_inherit_the_armed_environment(self) -> None:
        """Tripwire folder first on PYTHONPATH, the refused prefixes, a reports directory, no bytecode."""
        self.assertEqual(os.environ['PYTHONPATH'].split(os.pathsep)[0], isolation.CHILD_TRIPWIRE)
        self.assertIn(paths.canonical(str(paths.LIVE_BUDGET_ROOT)), json.loads(os.environ[children.CONFIG])['refused'])
        self.assertTrue(Path(os.environ[children.REPORTS]).is_dir())
        self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(sorted(path.name for path in Path(isolation.CHILD_TRIPWIRE).iterdir()), ['sitecustomize.py'])

    def test_a_python_child_is_refused_the_live_budget_root(self) -> None:
        """A read-only probe under the live authority exits 97 before the call and leaves one report."""
        environ, directory = self.private_reports()
        result = self.child(f'open({str(PROBE)!r})', environ)
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertIn(f'live-state child tripwire: open {paths.canonical(str(PROBE))}', result.stderr)
        self.assertEqual(len(children.reports(str(directory))), 1)

    def test_a_swallowed_refusal_still_exits_97_and_fails_the_parent_run(self) -> None:
        """(b) ``except BaseException`` cannot absorb it; an isolated run whose test expects failure gets an error."""
        environ, directory = self.private_reports()
        result = self.child(SWALLOW, environ)
        self.assertEqual((result.returncode, result.stdout), (97, ''), result.stderr)
        self.assertEqual(len(children.reports(str(directory))), 1)
        environ, directory = self.private_reports()
        run = self.child(NESTED_RUN, environ)
        self.assertEqual(run.returncode, 0, run.stderr)
        errors, failures, text = json.loads(run.stdout.splitlines()[-1])
        self.assertEqual((errors, failures), (1, 0), text)
        self.assertIn('a child process was refused live per-user state', text)
        self.assertEqual(len(children.reports(str(directory))), 1)

    def test_a_second_thread_is_refused_before_its_write(self) -> None:
        """(B1) Two barrier-released threads each write under a refused prefix: nothing is written, one report."""
        environ, decoy, reports = self.decoy()
        code = ('import threading\n'
                'barrier = threading.Barrier(2)\n'
                'def write(index):\n'
                '    barrier.wait()\n'
                f'    open({str(decoy)!r} + f"/written-{{index}}", "w").write("x")\n'
                'threads = [threading.Thread(target=write, args=(index,)) for index in range(2)]\n'
                '[thread.start() for thread in threads]\n'
                '[thread.join() for thread in threads]\n')
        for trial in range(20):
            with self.subTest(trial=trial):
                result = self.child(code, environ)
                self.assertEqual(result.returncode, 97, result.stderr)
                self.assertEqual(sorted(decoy.iterdir()), [])
        self.assertEqual(len(children.reports(str(reports))), 20)

    def test_an_install_failure_leaves_a_report(self) -> None:
        """(M3) A child whose prefixes are missing exits 97 and leaves an install-failure report naming its test."""
        environ, reports = self.private_reports()
        environ.pop(children.CONFIG)
        result = self.child('print("ran")', dict(environ, **{children.CURRENT: 'TEST.install_failure'}))
        self.assertEqual((result.returncode, result.stdout), (97, ''), result.stderr)
        lines = list(children.reports(str(reports)).values())
        self.assertEqual(len(lines), 1)
        self.assertIn('could not install', lines[0])
        self.assertIn('test TEST.install_failure', lines[0])

    def test_a_background_child_report_names_the_test_that_started_it(self) -> None:
        """(M3) A child started in one test and refused while another runs: the run fails and names the first."""
        environ, reports = self.private_reports()
        run = self.child(BACKGROUND_RUN, environ)
        self.assertEqual(run.returncode, 0, run.stderr)
        errors, text = json.loads(run.stdout.splitlines()[-1])
        self.assertGreaterEqual(errors, 1, text)
        self.assertIn('test __main__.BackgroundChild.test_1_starts_a_late_child', text)

    def test_a_late_refusal_after_the_run_is_kept_for_the_wrapper(self) -> None:
        """(M3) A child refused after its parent process exited leaves a report in the kept folder a wrapper checks."""
        environ, reports = self.private_reports()
        run = self.child(LATE_RUN, environ)
        self.assertEqual(run.returncode, 0, run.stderr)
        deadline = time.monotonic() + 20
        while not children.reports(str(reports)) and time.monotonic() < deadline:
            time.sleep(0.2)
        lines = list(children.reports(str(reports)).values())
        self.assertEqual(len(lines), 1, 'the late child left no report')
        self.assertIn('test __main__.LateChild.test_starts_a_child_that_outlives_the_run', lines[0])

    def test_a_missing_or_malformed_variable_exits_97(self) -> None:
        """(c) The child runs nothing when the parent's prefixes or reports directory are absent or wrong."""
        environ, _directory = self.private_reports()
        config = json.loads(environ[children.CONFIG])
        broken = {'no prefixes': {children.CONFIG: None}, 'not json': {children.CONFIG: '{'},
                  'empty prefixes': {children.CONFIG: json.dumps(dict(config, refused=[]))},
                  'relative prefix': {children.CONFIG: json.dumps(dict(config, writeRefused=['relative']))},
                  'no reports directory': {children.REPORTS: None}, 'relative reports': {children.REPORTS: 'reports'}}
        for label, change in broken.items():
            with self.subTest(label):
                merged = {key: value for key, value in {**environ, **change}.items() if value is not None}
                result = self.child('print("ran")', merged)
                self.assertEqual((result.returncode, result.stdout), (97, ''), result.stderr)
                self.assertIn('live-state child tripwire could not install', result.stderr)

    def test_the_tripwire_adds_no_module_and_no_path_entry(self) -> None:
        """(a) Against a plain child (same environment, not armed): no engine module, same modules and path."""
        plain = {key: value for key, value in os.environ.items() if key not in (children.CONFIG, children.REPORTS)}
        plain['PYTHONPATH'] = os.pathsep.join(entry for entry in os.environ['PYTHONPATH'].split(os.pathsep)
                                              if entry != isolation.CHILD_TRIPWIRE)
        armed_modules, armed_path = json.loads(self.child(STATE).stdout)
        plain_modules, plain_path = json.loads(self.child(STATE, plain).stdout)
        self.assertEqual([name for name in armed_modules if name in ENGINE_MODULES], [])
        self.assertEqual(outside_stdlib(armed_modules), outside_stdlib(plain_modules))
        self.assertEqual(sorted(set(armed_modules) - set(plain_modules)), ARMED_EXTRA)
        self.assertEqual([entry for entry in armed_path if entry != isolation.CHILD_TRIPWIRE], plain_path)

    def test_a_child_imports_the_pool_client_from_its_own_first_path(self) -> None:
        """(d) The base_pool_4a15560 case: a folder a child puts first on sys.path supplies native_work_lease."""
        folder = Path(tempfile.mkdtemp(prefix='p0-own-first-path-')).resolve()
        self.addCleanup(shutil.rmtree, folder)
        (folder / 'native_work_lease.py').write_text('MARK = "TEST stub"\n')
        code = f'import sys\nsys.path.insert(0, {str(folder)!r})\nimport native_work_lease\nprint(native_work_lease.__file__)\n'
        result = self.child(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), folder / 'native_work_lease.py')

    def test_a_child_with_its_own_private_root_is_not_refused(self) -> None:
        """A child that gives itself a private authority root writes there without refusal."""
        code = ('import pathlib, shutil, tempfile\n'
                'from studio import native_budget_store as store\n'
                'base = pathlib.Path(tempfile.mkdtemp(prefix="sniper-child-root-"))\n'
                'store.default_root = lambda: base / "production-budgets"\n'
                'store.default_root().mkdir()\n'
                '(store.default_root() / "probe.json").write_text("{}")\n'
                'shutil.rmtree(base)\n'
                'print("private-ok")\n')
        result = self.child(code)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, 'private-ok'), result.stderr)

    def test_the_parent_process_does_not_load_the_tripwire(self) -> None:
        """The test process itself is guarded by the in-process hook, not by the child tripwire."""
        module = sys.modules.get('sitecustomize')
        location = getattr(module, '__file__', '') or ''
        self.assertFalse(location.startswith(isolation.CHILD_TRIPWIRE), location)


if __name__ == '__main__':
    unittest.main()
