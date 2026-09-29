"""The child tripwire holds against a crafted cache file, a broken stderr, a fork and an AF_UNIX bind.

C1FIX-REVIEW delta D2, D3, D4 and D7, CS4-REVIEW mi5, and M-C4F3 (which process names its kept reports folder).
Every child here but the M-C4F3 pair is armed like any test child, but its refused prefixes also hold a decoy
folder of this test's own, so the only paths a child tries to write are decoy paths; reports go to this test's own
folder. The deliberately unguarded children (the D2 control, with no bytecode prefix, and the mi5 control, with a
crafted inherited prefix) write a decoy file only. The M-C4F3 pair runs in a closed environment, as a supervised
owner's child does, with its temporary folder inside a folder of this test.
"""
from __future__ import annotations

import _live_state_isolation as isolation
import _live_state_children as children
import _live_state_paths as paths

import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ChildHardeningTests(unittest.TestCase):
    """Refusal survives the ways C1-fix-2 could still be bypassed or hang."""

    def folder(self, prefix: str) -> Path:
        """A fresh canonical temporary folder of this test's own."""
        path = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
        self.addCleanup(shutil.rmtree, path)
        return path

    def armed(self) -> tuple[dict, Path, Path]:
        """(environment, decoy folder, reports folder): the armed environment with the decoy added to the refused set."""
        decoy, reports = self.folder('p0-decoy-'), self.folder('p0-child-reports-')
        config = json.loads(os.environ[children.CONFIG])
        config['refused'] = sorted({*config['refused'], paths.canonical(str(decoy))})
        environ = dict(os.environ, **{children.CONFIG: json.dumps(config), children.REPORTS: str(reports)})
        return environ, decoy, reports

    def child(self, code: str, environ: dict) -> subprocess.CompletedProcess:
        """One Python child; a hang is a failure (the timeout raises)."""
        return subprocess.run([sys.executable, '-B', '-c', code], env=environ, capture_output=True, text=True,
                              timeout=60, check=False)

    def assert_refused(self, result: subprocess.CompletedProcess, decoy: Path, reports: Path, count: int = 1) -> None:
        """Exit 97, nothing continued, nothing written under the decoy, the expected number of reports."""
        self.assertEqual((result.returncode, result.stdout), (97, ''), result.stderr)
        self.assertEqual(sorted(decoy.iterdir()), [])
        self.assertEqual(len(children.reports(str(reports))), count)

    def test_a_crafted_cached_sitecustomize_does_not_disable_the_tripwire(self) -> None:
        """(D2) An unchecked-hash pyc of an empty module beside the tripwire: ignored under the armed prefix."""
        environ, decoy, reports = self.armed()
        copy = self.folder('p0-tripwire-copy-')
        shutil.copy(Path(isolation.CHILD_TRIPWIRE) / 'sitecustomize.py', copy / 'sitecustomize.py')
        empty = copy / 'empty.py'
        empty.write_text('')
        cache = copy / '__pycache__' / f'sitecustomize.{sys.implementation.cache_tag}.pyc'
        py_compile.compile(str(empty), cfile=str(cache), invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        empty.unlink()
        entries = [str(copy)] + [entry for entry in environ['PYTHONPATH'].split(os.pathsep)[1:]]
        environ['PYTHONPATH'] = os.pathsep.join(entries)
        code = f'open({str(decoy / "written")!r}, "w").write("x")\nprint("wrote")\n'
        control = dict(environ)
        control.pop('PYTHONPYCACHEPREFIX')
        self.assertEqual(self.child(code, control).returncode, 0, 'the crafted pyc no longer bypasses; the test is stale')
        (decoy / 'written').unlink()
        self.assertTrue(Path(environ['PYTHONPYCACHEPREFIX']).is_dir())
        self.assert_refused(self.child(code, environ), decoy, reports)

    def test_an_inherited_bytecode_prefix_is_replaced_never_trusted(self) -> None:
        """(CS4-REVIEW mi5) A prefix holding a crafted sitecustomize pyc: effective until arm() replaces it."""
        environ, decoy, reports = self.armed()
        crafted = self.folder('p0-crafted-prefix-')
        source_dir = Path(isolation.CHILD_TRIPWIRE)
        cache = crafted / str(source_dir).lstrip('/') / f'sitecustomize.{sys.implementation.cache_tag}.pyc'
        cache.parent.mkdir(parents=True)
        empty = crafted / 'empty.py'
        empty.write_text('')
        mode = py_compile.PycInvalidationMode.UNCHECKED_HASH
        py_compile.compile(str(empty), cfile=str(cache), invalidation_mode=mode)
        code = f'open({str(decoy / "written")!r}, "w").write("x")\nprint("wrote")\n'
        environ['PYTHONPYCACHEPREFIX'] = str(crafted)
        stale = 'the crafted prefix no longer bypasses; the test is stale'
        self.assertEqual(self.child(code, environ).returncode, 0, stale)
        (decoy / 'written').unlink()
        children.arm(paths, environ)
        self.addCleanup(shutil.rmtree, environ['PYTHONPYCACHEPREFIX'], True)
        self.assertNotEqual(environ['PYTHONPYCACHEPREFIX'], str(crafted))
        self.assertEqual(os.listdir(environ['PYTHONPYCACHEPREFIX']), [])
        self.assert_refused(self.child(code, environ), decoy, reports)

    def test_a_refusal_with_no_stderr_still_exits_97_with_a_report(self) -> None:
        """(D3) sys.stderr is None and the refusal is caught: exit 97, one report, nothing written."""
        environ, decoy, reports = self.armed()
        code = (f'import sys\nsys.stderr = None\ntry:\n    open({str(decoy / "x")!r}, "w")\n'
                'except BaseException:\n    pass\nprint("continued")\n')
        self.assert_refused(self.child(code, environ), decoy, reports)

    def test_a_refusal_whose_stderr_raises_still_exits_97_with_a_report(self) -> None:
        """(D3) sys.stderr.write raises and the refusal is caught: exit 97, one report, nothing written."""
        environ, decoy, reports = self.armed()
        code = ('import sys\nclass Raising:\n    def write(self, text):\n        raise RuntimeError("TEST")\n'
                '    def flush(self):\n        raise RuntimeError("TEST")\n'
                f'sys.stderr = Raising()\ntry:\n    open({str(decoy / "x")!r}, "w")\n'
                'except BaseException:\n    pass\nprint("continued")\n')
        self.assert_refused(self.child(code, environ), decoy, reports)

    def test_a_fork_during_the_report_window_does_not_hang(self) -> None:
        """(D4) A thread holds the gate while its stderr write blocks; a forked child is refused on its own."""
        environ, decoy, reports = self.armed()
        code = ('import os, sys, threading, time, warnings\nwarnings.simplefilter("ignore")\n'
                'class Slow:\n    def write(self, text):\n        time.sleep(2)\n    def flush(self):\n        pass\n'
                f'sys.stderr = Slow()\n'
                f'threading.Thread(target=lambda: open({str(decoy / "a")!r}, "w")).start()\n'
                'time.sleep(0.5)\nif os.fork() == 0:\n'
                f'    open({str(decoy / "b")!r}, "w")\n    os._exit(0)\n'
                'time.sleep(30)\n')
        self.assert_refused(self.child(code, environ), decoy, reports, count=2)

    def test_an_af_unix_bind_under_a_refused_prefix_is_refused(self) -> None:
        """(D7) socket.bind of an AF_UNIX path creates a file: refused before the call."""
        environ, decoy, reports = self.armed()
        code = (f'import socket\ns = socket.socket(socket.AF_UNIX)\ntry:\n    s.bind({str(decoy / "s")!r})\n'
                'except BaseException:\n    pass\nprint("continued")\n')
        self.assert_refused(self.child(code, environ), decoy, reports)

    def test_only_a_test_run_names_its_kept_reports_folder(self) -> None:
        """(M-C4F3) An importer that starts no test run keeps its folder silently, so a supervised child's log stays
        its own; an unwrapped test run names its kept folder on stderr at exit."""
        temporary, tests = self.folder('p0-own-reports-'), Path(__file__).resolve().parent
        environ = {'PATH': '/usr/bin:/bin', 'TMPDIR': str(temporary),
                   'PYTHONPATH': os.pathsep.join([str(tests.parent), str(tests)])}
        quiet = self.child('import _live_state_isolation\nprint("status")\n', environ)
        empty_run = 'unittest.TextTestRunner().run(unittest.TestSuite())'
        run = self.child(f'import _live_state_isolation, unittest\n{empty_run}\n', environ)
        self.assertEqual((quiet.returncode, quiet.stdout, quiet.stderr), (0, 'status\n', ''))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f'live-state isolation: child refusal reports are kept in {temporary}/', run.stderr)
        kept = [path for path in temporary.iterdir() if path.name.startswith('sniper-child-refusals-')]
        self.assertEqual(len(kept), 2)


if __name__ == '__main__':
    unittest.main()
