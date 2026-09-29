"""Python child processes started by tests carry the live-state tripwire (tests/_child_live_state).

T0's in-process audit hook cannot follow a child; ``_live_state_children.arm`` arms every child it can: the
tripwire folder first on the inherited PYTHONPATH, the parent's refused prefixes as JSON, a reports directory and
PYTHONDONTWRITEBYTECODE. These tests prove that a refused child exits 97 and leaves a report that fails the parent
run even when the child swallows everything, that the tripwire changes no child's modules or path, that a missing
or malformed variable fails closed, that the child's matcher refuses what the parent's refuses, and that the test
process itself does not load the child module (p0-records E-001; reviews/CS1-REVIEW.md F1, F2, ST-5). Every probe
of a live path is read-only and names a file that does not exist; a child that is meant to be refused reports into
this test's own directory, never into the run's.
"""
from __future__ import annotations

import _live_state_isolation as isolation
import _live_state_children as children
import _live_state_paths as paths

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
ENGINE_MODULES = ('native_work_lease', 'native_render_processes', 'headless', 'headless.durable_files')
BASE_POOL = TESTS / 'fixtures' / 'base_pool_4a15560'
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
        directory = Path(tempfile.mkdtemp(prefix='p0-child-reports-'))
        self.addCleanup(shutil.rmtree, directory)
        return dict(os.environ, **{children.REPORTS: str(directory)}), directory

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
        self.assertEqual([entry for entry in armed_path if entry != isolation.CHILD_TRIPWIRE], plain_path)

    def test_a_child_imports_the_pool_client_from_its_own_first_path(self) -> None:
        """(d) The base_pool_4a15560 case: a folder a child puts first on sys.path supplies native_work_lease."""
        code = f'import sys\nsys.path.insert(0, {str(BASE_POOL)!r})\nimport native_work_lease\nprint(native_work_lease.__file__)\n'
        result = self.child(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), BASE_POOL / 'native_work_lease.py')

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


class ChildMatcherParityTests(unittest.TestCase):
    """The child's stdlib matcher and ``_live_state_paths.refused_path`` refuse exactly the same spellings."""

    def test_every_spelling_gets_the_same_verdict(self) -> None:
        """Case, ``//``, the Data-volume firmlink, /private aliases, reads versus writes, dir_fd and renames."""
        spec = importlib.util.spec_from_file_location('p0_child_matcher', Path(isolation.CHILD_TRIPWIRE) / 'sitecustomize.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # another module name: the hook is not installed here
        tripwire = module.Tripwire(module.load_config(os.environ[children.CONFIG]), '')
        directory = tempfile.mkdtemp(prefix='p0-matcher-')
        self.addCleanup(shutil.rmtree, directory)
        descriptor = os.open(directory, os.O_RDONLY)
        self.addCleanup(os.close, descriptor)
        live, pool = str(paths.LIVE_BUDGET_ROOT), str(paths.LIVE_POOL_ROOT)
        names = [live + '/x', live.upper() + '/X', '/' + live + '/x', '/System/Volumes/Data' + live + '/x', pool + '/x',
                 pool.removeprefix('/private') + '/x', str(paths.LIVE_POOL_RECORDS) + '/r.json',
                 str(paths.ACCOUNT_STATE) + '/runtimes/a', str(paths.ACCOUNT_HOME) + '/other', directory + '/y']
        cases = [('open', (name, 'r', os.O_RDONLY)) for name in names] + [
            ('open', (name, 'w', os.O_WRONLY | os.O_CREAT)) for name in names] + [
            ('os.listdir', (name,)) for name in names] + [('os.rename', (directory + '/a', name, -1, -1)) for name in names]
        cases += [('os.mkdir', ('relative', 0o777, descriptor)), ('os.remove', ('relative', descriptor))]
        verdicts = [(event, args[:2], tripwire.refused(event, args), paths.refused_path(event, args)) for event, args in cases]
        self.assertEqual([row for row in verdicts if row[2] != row[3]], [])
        self.assertGreaterEqual(sum(row[3] is not None for row in verdicts), 25)


class InProcessRootTests(unittest.TestCase):
    """(e) CS1-REVIEW ST-5: one module object per owner; late imports bind this test's private root."""

    def test_one_owner_module_object_each_and_a_late_import_is_private(self) -> None:
        """No alias copy of an owner exists, and a function-level import returns the replacement."""
        import native_work_lease
        from studio import native_budget_store
        owners = {Path(native_budget_store.__file__).resolve(), Path(native_work_lease.__file__).resolve()}
        names = sorted(name for name, module in list(sys.modules.items())
                       if getattr(module, '__file__', None) and Path(module.__file__).resolve() in owners)
        self.assertEqual(names, ['native_work_lease', 'studio.native_budget_store'])
        namespace: dict = {}
        exec('from studio.native_budget_store import default_root', namespace)
        self.assertIs(namespace['default_root'], isolation.isolated_budget_root)

    def test_the_motion_review_late_import_resolves_this_tests_private_root(self) -> None:
        """native_motion_review imports default_root inside a function; the root it passes on is private."""
        from studio import native_motion_review
        directory = Path(tempfile.mkdtemp(prefix='p0-motion-review-')).resolve()  # the review reader wants canonical
        self.addCleanup(shutil.rmtree, directory)
        bundle = directory / 'reviews.json'
        bundle.write_text(json.dumps({'reviews': [{'inspection': {'fixture': 'TEST', 'approves': ['motion']}}]}))
        seen: list = []
        with mock.patch('studio.native_budget_registry.resolve_binding', side_effect=lambda root, _project: seen.append(root)):
            native_motion_review.require_typed_short_reviews(bundle, directory)
        self.assertEqual(seen, [isolation.isolated_budget_root()])
        self.assertTrue(seen[0].is_relative_to(isolation.STATE.scopes[-1].base()), seen[0])
        self.assertIsNone(paths.refused_path('open', (str(seen[0] / 'probe.json'), 'r', os.O_RDONLY)))


if __name__ == '__main__':
    unittest.main()
