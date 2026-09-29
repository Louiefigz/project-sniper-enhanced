"""Guard: no test reaches the operator's live budget authority, pool record or pool namespace.

The private roots and the audit hook come from _live_state_isolation.py (live paths in
_live_state_paths.py). These tests prove that the engine's bindings resolve to per-test private
roots and that the hook refuses the live paths, in any spelling, before the system call, even
when a test swallows the refusal. Fixture-level behavior runs in a fresh process over decoy
roots (fixtures/live_state_probe.py). Every in-process probe of a real live path is read-only
and names an entry that does not exist, so a broken hook produces FileNotFoundError, never a
read or write of real state. The static coverage checks are in test_live_state_coverage.py.
"""
from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _live_state_isolation as isolation
import _live_state_paths as paths
import native_batch  # noqa: F401  (loads the batch CLI closure under the isolation; src has no by-name root there)
import native_work_lease
import native_work_qualification
from _private_budget_root import rebind
from studio import native_budget_binding, native_budget_exporter, native_budget_owner, native_budget_store
from studio.native_budget_registry import resolve_binding
from studio.native_budget_store import ensure_root

PROBE = 'guard-probe-that-does-not-exist'
PROBE_SCRIPT = Path(__file__).resolve().parent / 'fixtures' / 'live_state_probe.py'


def run_probe(case: type[unittest.TestCase]) -> unittest.TestResult:
    """Run a locally defined probe TestCase (never collected by discovery) and return its result."""
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(case).run(result)
    return result


class PrivateRootTests(unittest.TestCase):
    """Every engine binding of the two roots resolves to this test's private directories."""

    def test_every_default_root_binding_is_this_tests_private_root(self) -> None:
        """The store and each by-name import give the same private, non-live authority root."""
        root = isolation.isolated_budget_root()
        from studio import native_long_budget  # src's module-level by-name importers (P0 M-010 adaptation)
        for module in (native_budget_store, native_budget_binding, native_budget_exporter,
                       native_budget_owner, native_long_budget):
            self.assertEqual(module.default_root(), root, module.__name__)
        self.assertIsNone(paths.refused_path('os.mkdir', (str(root), 0o700, None)))
        self.assertEqual(root.parent.stat().st_mode & 0o777, 0o700)

    def test_no_loaded_module_holds_a_live_root_function_under_any_name(self) -> None:
        """Every attribute that is the engine's own function object was replaced."""
        originals = (isolation.ORIGINAL_DEFAULT_ROOT, isolation.ORIGINAL_STATE_ROOT)
        holders = [f'{name}.{key}' for name, module in list(sys.modules.items())
                   if name not in ('_live_state_isolation', 'tests._live_state_isolation')
                   for key, value in list(getattr(module, '__dict__', {}).items())
                   if any(value is original for original in originals)]
        self.assertEqual(holders, [])

    def test_rebind_replaces_an_alias_imported_under_another_name(self) -> None:
        """Identity, not the attribute name, decides what is replaced; a chosen root is kept."""
        owner, importer = types.ModuleType('t0_probe_owner'), types.ModuleType('t0_probe_importer')
        exec('def root():\n    return "live"\n', owner.__dict__)
        importer.budget_root = owner.root
        self.enterContext(mock.patch.dict(sys.modules, {owner.__name__: owner, importer.__name__: importer}))
        self.assertTrue(rebind(owner, 'root', lambda: 'private'))
        self.assertEqual((owner.root(), importer.budget_root()), ('private', 'private'))
        self.assertFalse(rebind(owner, 'root', lambda: 'other'))

    def test_pool_namespace_and_host_record_are_private(self) -> None:
        """A private namespace also means the host qualification record is never read."""
        self.assertEqual(native_work_lease.state_root(), isolation.isolated_state_root())
        self.assertNotEqual(native_work_lease.state_root(), native_work_lease.default_state_root())
        self.assertIsNone(native_work_qualification.record_directory())

    def test_unbuilt_fixture_project_is_unbudgeted_on_a_private_root(self) -> None:
        """The failing export path: a manifest without projectHash is only identified when batches exist."""
        project = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'project'
        project.mkdir()
        (project / 'PROJECT-MANIFEST.json').write_text(json.dumps({'files': []}))
        self.assertIsNone(resolve_binding(native_budget_store.default_root(), project))
        native_budget_exporter.refuse_if_budgeted(project)

    def test_live_paths_are_the_engine_formulas(self) -> None:
        """The guarded paths are exactly where the real functions point for this account."""
        home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        with mock.patch('pwd.getpwuid', return_value=SimpleNamespace(pw_dir=str(home))):
            real_root = isolation.ORIGINAL_DEFAULT_ROOT()
            with mock.patch.object(native_work_lease, 'state_root', native_work_lease.default_state_root):
                real_records = native_work_qualification.record_directory()
        account = Path(pwd.getpwuid(os.getuid()).pw_dir)
        self.assertEqual(paths.LIVE_BUDGET_ROOT, account / real_root.relative_to(home))
        self.assertEqual(paths.LIVE_POOL_RECORDS, account / real_records.relative_to(home))
        self.assertEqual(paths.LIVE_POOL_ROOT, native_work_lease.default_state_root())


class PerTestRootTests(unittest.TestCase):
    """Roots are fresh for each test and removed after it."""

    def test_each_test_gets_fresh_roots_removed_after_it(self) -> None:
        """Two probe tests see different roots from each other and from this test; none survive."""
        seen: list[tuple[Path, Path]] = []

        class Probe(unittest.TestCase):
            def test_a(self) -> None:
                """Use both roots, then report where they were."""
                ensure_root(native_budget_store.default_root())
                native_work_lease.state_root().mkdir(mode=0o700)
                seen.append((native_budget_store.default_root(), native_work_lease.state_root()))

            test_b = test_a

        result = run_probe(Probe)
        self.assertTrue(result.wasSuccessful(), result.errors)
        roots = [path for pair in seen for path in pair]
        self.assertEqual(len(set(roots)), 4)
        self.assertNotIn(native_budget_store.default_root(), roots)
        self.assertFalse(any(path.exists() or path.parent.exists() for path in roots))


def _spelled(path: Path, spelling: str) -> str:
    """One alternative spelling of a live path (all name the same folder on this Mac)."""
    text = f'{path}/{PROBE}'
    return {'double-slash': '/' + text, 'case': text.swapcase(), 'firmlink': '/System/Volumes/Data' + text,
            'tmp': text.removeprefix('/private')}[spelling]


class LiveTouchRefusalTests(unittest.TestCase):
    """The audit hook refuses the live paths before the system call and fails the test."""

    def assert_refused(self, result: unittest.TestResult, count: int) -> None:
        """Each probe errored with LiveStateTouched, never with a real file-system error."""
        self.assertEqual(result.testsRun, count)
        self.assertEqual(len(result.errors), count, result.errors)
        for _test, text in result.errors:
            self.assertIn('LiveStateTouched', text)
            self.assertNotIn('FileNotFoundError', text)

    def test_live_roots_are_refused_in_every_spelling(self) -> None:
        """Open, listing and scandir of each live root, literal or respelled, are refused."""
        calls = [lambda: open(paths.LIVE_BUDGET_ROOT / PROBE / 'authority.json', 'rb'),
                 lambda: os.scandir(paths.LIVE_BUDGET_ROOT / PROBE),
                 lambda: open(paths.LIVE_POOL_RECORDS / PROBE, 'rb'),
                 lambda: os.listdir(paths.LIVE_POOL_ROOT / PROBE),
                 lambda: open(paths.ACCOUNT_STATE / PROBE / 'written', 'wb'),
                 lambda: os.listdir(_spelled(paths.LIVE_POOL_ROOT, 'tmp')),
                 *(lambda spelling=spelling: os.listdir(_spelled(paths.LIVE_BUDGET_ROOT, spelling))
                   for spelling in ('double-slash', 'case', 'firmlink'))]
        probe = type('Probe', (unittest.TestCase,), {f'test_{index}': lambda self, call=call: call()
                                                     for index, call in enumerate(calls)})
        self.assert_refused(run_probe(probe), len(calls))

    def test_installed_runtimes_stay_readable_but_never_writable(self) -> None:
        """Retained-evidence tests may hash installed tools; nothing may change them."""
        tool = str(paths.ACCOUNT_STATE / 'runtimes' / PROBE / 'bin' / 'ffmpeg')
        self.assertIsNone(paths.refused_path('open', (tool, 'rb', os.O_RDONLY)))
        self.assertEqual(paths.refused_path('open', (tool, 'r+b', os.O_RDWR)), paths.canonical(tool))
        self.assertEqual(paths.refused_path('os.remove', (tool, None)), paths.canonical(tool))
        self.assertEqual(paths.refused_path('os.rename', ('/private/tmp/elsewhere', tool, None, None)),
                         paths.canonical(tool))

    def test_swallowed_refusal_still_fails_the_test(self) -> None:
        """Catching the refusal (even as BaseException) cannot turn the test green."""
        class Probe(unittest.TestCase):
            def test_swallow(self) -> None:
                """Catch the refusal and carry on."""
                try:
                    open(paths.LIVE_BUDGET_ROOT / PROBE, 'rb')
                except BaseException:
                    pass

        self.assert_refused(run_probe(Probe), 1)

    def test_refusal_types(self) -> None:
        """In a test it is a BaseException; in a fixture unittest must be able to report it."""
        self.assertFalse(issubclass(isolation.LiveStateTouched, Exception))
        self.assertTrue(issubclass(isolation.LiveStateFixtureTouched, Exception))
        self.assertTrue(issubclass(isolation.LiveStateScopeError, Exception))


class DescriptorResolutionTests(unittest.TestCase):
    """Relative paths under a directory descriptor, and descriptors themselves, are resolved."""

    def setUp(self) -> None:
        """Treat a private temporary folder as live for the duration of the test."""
        self.live = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.descriptor = os.open(self.live, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.descriptor)
        self.enterContext(mock.patch.object(paths, 'REFUSED_PREFIXES', (paths.canonical(str(self.live)),)))

    def test_dir_fd_and_descriptor_paths_are_resolved(self) -> None:
        """mkdir/rename relative to a live dir fd and listdir(fd) name the live folder."""
        expected = paths.canonical(str(self.live / 'child'))
        self.assertEqual(paths.refused_path('os.mkdir', ('child', 0o700, self.descriptor)), expected)
        self.assertEqual(paths.refused_path('os.rename', ('/private/tmp/x', 'child', None, self.descriptor)), expected)
        self.assertEqual(paths.refused_path('os.listdir', (self.descriptor,)), paths.canonical(str(self.live)))
        self.assertIsNone(paths.refused_path('os.mkdir', ('child', 0o700, -1)))

    def test_the_installed_hook_refuses_a_dir_fd_mkdir(self) -> None:
        """End to end: os.mkdir(..., dir_fd=) under a live folder errors before creating anything."""
        live, descriptor = self.live, self.descriptor

        class Probe(unittest.TestCase):
            def test_mkdir(self) -> None:
                """Create a folder through the directory descriptor."""
                os.mkdir('created', dir_fd=descriptor)

        result = run_probe(Probe)
        self.assertEqual(len(result.errors), 1, result.errors)
        self.assertIn('LiveStateTouched', result.errors[0][1])
        self.assertFalse((live / 'created').exists())


class FixtureLevelTests(unittest.TestCase):
    """Class fixtures, imports and reloads, each in a fresh process over decoy roots."""

    def probe(self, case: str) -> tuple[int, dict, str]:
        """Run one probe case; return its exit status, JSON line and stderr."""
        decoy = self.enterContext(tempfile.TemporaryDirectory())
        done = subprocess.run([sys.executable, '-B', str(PROBE_SCRIPT), case, decoy], capture_output=True,
                              text=True, timeout=120, cwd=PROBE_SCRIPT.parents[2])
        lines = done.stdout.strip().splitlines()
        return done.returncode, json.loads(lines[-1]) if lines else {}, done.stderr

    def test_class_fixtures_get_no_shared_root(self) -> None:
        """A fixture's root request is a class-level error; later classes still run."""
        status, report, _ = self.probe('shared')
        self.assertEqual(status, 0)
        self.assertIn('LiveStateScopeError', report['errors'][0][1])
        self.assertEqual((report['testsRun'], report['seen']), (1, {'laterRan': True}))

    def test_fixture_refusals_are_reported_not_fatal(self) -> None:
        """A propagated refusal errors its class; a swallowed one fails the run at its end."""
        _, propagated, _ = self.probe('propagate')
        self.assertIn('LiveStateFixtureTouched', propagated['errors'][0][1])
        self.assertTrue(propagated['seen']['laterRan'])
        _, swallowed, _ = self.probe('swallow')
        self.assertFalse(swallowed['ok'])
        self.assertEqual(swallowed['errors'][0][0], 'live-state isolation (outside test methods)')
        status, _, stderr = self.probe('import-touch')
        self.assertEqual(status, 1)
        self.assertIn('unreported touches outside test methods', stderr)

    def test_reloading_or_reimporting_keeps_the_installed_state(self) -> None:
        """A reload during a run keeps working; a second import shares the one state."""
        _, reloaded, _ = self.probe('reload')
        self.assertTrue(reloaded['ok'], reloaded)
        self.assertNotIn(str(Path(reloaded['decoyBudget']).parent), reloaded['seen']['afterReload'])
        _, twice, _ = self.probe('twice')
        self.assertEqual({key: twice[key] for key in ('distinctModule', 'sharedState', 'originalIsEngine',
                                                      'wrapperInstalled')}, dict.fromkeys(
            ('distinctModule', 'sharedState', 'originalIsEngine', 'wrapperInstalled'), True))


    def test_supervised_scripts_get_a_private_budget_root_and_the_real_pool(self) -> None:
        """use_private_budget_root() replaces every budget binding and leaves the pool functions alone."""
        code = ('import json, sys; sys.path[:0] = sys.argv[1:3]\n'
                'import native_work_lease\n'
                'from studio import native_budget_exporter, native_budget_store\n'
                'from _private_budget_root import use_private_budget_root\n'
                'use_private_budget_root()\n'
                'root = native_budget_store.default_root()\n'
                'print(json.dumps({"root": str(root), "same": native_budget_exporter.default_root() == root,\n'
                '    "poolIsEngine": native_work_lease.state_root.__module__ == "native_work_lease"}))\n')
        roots = (str(PROBE_SCRIPT.parents[2]), str(PROBE_SCRIPT.parents[1]))
        done = subprocess.run([sys.executable, '-B', '-c', code, *roots], capture_output=True, text=True,
                              timeout=120, check=True)
        report = json.loads(done.stdout)
        self.assertTrue(report['same'] and report['poolIsEngine'], report)
        self.assertIsNone(paths.refused_path('os.mkdir', (report['root'], 0o700, None)))
        self.assertIn('sniper-supervised-budget-', report['root'])


if __name__ == '__main__':
    unittest.main()
