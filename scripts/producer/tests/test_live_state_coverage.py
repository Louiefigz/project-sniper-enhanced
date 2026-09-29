"""Static guard: every way a test can reach the live budget or pool state is isolated or reviewed.

1. A test module whose imports (at any depth) can reach an owner installs the isolation at
   import time.
2. selftest.py installs it before it discovers any test module.
3. Dynamic imports and child launches, which the import closure cannot follow, are listed
   with a reviewed reason in _live_state_child_allowlist.py.
4. The supervised real-media scripts take a private budget root first thing in ``__main__``
   and keep the real host pool.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from _live_state_child_allowlist import REVIEWED
from _live_state_import_graph import ISOLATION, OWNERS, PRODUCER, TESTS, ImportGraph, dynamic_sites

SUPERVISED = ('native_perf_fixture.py', 'native_route_canary_fixture.py')


def _call_name(node: ast.stmt) -> str | None:
    """The function name of a bare call statement, else None."""
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        function = node.value.func
        return function.attr if isinstance(function, ast.Attribute) else getattr(function, 'id', None)
    return None


def _main_block(tree: ast.Module) -> list[ast.stmt]:
    """The body of the module's ``if __name__ == '__main__':`` block."""
    blocks = [node.body for node in tree.body if isinstance(node, ast.If) and '__main__' in ast.unparse(node.test)]
    if len(blocks) != 1:
        raise AssertionError(f'expected one __main__ block, found {len(blocks)}')
    return blocks[0]


def _statement_calls(node: ast.stmt) -> set[str]:
    """Every function or method name called anywhere in one statement."""
    return {call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
            for call in ast.walk(node) if isinstance(call, ast.Call)}


class ImportCoverageTests(unittest.TestCase):
    """A test module that can reach an owner installs the isolation when it is imported."""

    def test_modules_that_can_reach_the_owners_install_the_isolation(self) -> None:
        """Any-depth imports decide reach; only module-level imports count as installing it."""
        graph, missing, reaching = ImportGraph(), [], 0
        for path in sorted(TESTS.glob('test_*.py')):
            if not graph.closure(path.stem, top_only=False) & OWNERS:
                continue
            reaching += 1
            if ISOLATION not in graph.closure(path.stem, top_only=True):
                missing.append(path.name)
        self.assertGreater(reaching, 50)
        self.assertEqual(missing, [], 'add `import _live_state_isolation  # noqa: F401` to these modules')

    def test_aggregate_runner_installs_the_isolation_before_discovery(self) -> None:
        """selftest.py's __main__ calls _isolate_live_state() as a statement before discover()."""
        tree = ast.parse((PRODUCER / 'selftest.py').read_text())
        function = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == '_isolate_live_state']
        self.assertEqual(len(function), 1)
        imported = {alias.name for node in ast.walk(function[0]) if isinstance(node, ast.Import)
                    for alias in node.names}
        self.assertIn(ISOLATION, imported)
        body = _main_block(tree)
        isolate = [index for index, node in enumerate(body) if _call_name(node) == '_isolate_live_state']
        discover = [index for index, node in enumerate(body) if 'discover' in _statement_calls(node)]
        self.assertTrue(isolate and discover, 'selftest.py must isolate, then discover')
        self.assertLess(isolate[0], discover[0])


class ReviewedDynamicSiteTests(unittest.TestCase):
    """Dynamic imports and child launches are reviewed one by one."""

    def test_dynamic_imports_and_child_launches_are_reviewed(self) -> None:
        """The files that use them are exactly the reviewed list; new ones need a reason."""
        found = {path.name for path in sorted([*TESTS.glob('test_*.py'), *TESTS.glob('_*.py')])
                 if dynamic_sites(path)}
        self.assertEqual(sorted(found - set(REVIEWED)), [],
                         'review each new child launch or dynamic import (can it reach the budget or pool '
                         'owners?), give a child its own roots, then add it to _live_state_child_allowlist.py')
        self.assertEqual(sorted(set(REVIEWED) - found), [], 'remove rows for files that no longer use them')

    def test_the_scan_sees_each_kind_of_site(self) -> None:
        """A child launch and each dynamic-import form are detected."""
        sample = TESTS / '_live_state_import_graph.py'
        self.assertEqual(dynamic_sites(sample), set())
        self.assertEqual(dynamic_sites(TESTS / '_native_pool_fixture.py'), {'sys.executable'})  # test_native_batch_cli.py returns at M-020
        self.assertEqual(dynamic_sites(TESTS / 'test_program_mix_registry.py'), {'__import__'})
        self.assertEqual(dynamic_sites(TESTS / 'test_grade_project_input.py'), {'run_path'})


class SupervisedScriptTests(unittest.TestCase):
    """Real-media scripts get a private budget authority but keep the host pool."""

    def supervised(self) -> list[Path]:
        """Every supervised real-media script in tests/."""
        scripts = [path for path in TESTS.glob('*_integration.py') if not path.name.startswith('test_')]
        return sorted([*scripts, *(TESTS / name for name in SUPERVISED)])

    def test_each_takes_a_private_budget_root_first_in_main(self) -> None:
        """The first statement of __main__ is use_private_budget_root()."""
        scripts = self.supervised()
        self.assertGreaterEqual(len(scripts), 9)
        for script in scripts:
            with self.subTest(script=script.name):
                body = _main_block(ast.parse(script.read_text()))
                self.assertEqual(_call_name(body[0]), 'use_private_budget_root')

    def test_none_installs_the_test_isolation(self) -> None:
        """The host pool stays real for supervised renders: no private pool, no audit hook."""
        graph = ImportGraph()
        for script in self.supervised():
            with self.subTest(script=script.name):
                self.assertNotIn(ISOLATION, graph.closure(script.stem, top_only=False))


if __name__ == '__main__':
    unittest.main()
