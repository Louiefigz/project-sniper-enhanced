"""Python child processes started by tests carry the live-state tripwire (tests/_child_live_state).

T0's in-process audit hook cannot follow a child; ``_live_state_isolation`` arms every child it can by putting
the tripwire folder first on the inherited PYTHONPATH. These tests prove a child is refused the live authority,
that a child with its own private root is unaffected, and that the test process itself does not load the child
module. Every probe of a live path is read-only and names a file that does not exist.
"""
from __future__ import annotations

import _live_state_isolation as isolation
import _live_state_paths as paths

import os
import subprocess
import sys
import unittest


class ChildTripwireTests(unittest.TestCase):
    """Python children inherit a refusing audit hook through PYTHONPATH (tests/_child_live_state)."""

    def child(self, code: str) -> subprocess.CompletedProcess:
        """Run one Python child with this process's environment (which carries the armed PYTHONPATH)."""
        return subprocess.run([sys.executable, '-B', '-c', code], env=dict(os.environ), capture_output=True,
                              text=True, timeout=60, check=False)

    def test_children_inherit_the_tripwire_first_on_their_path(self) -> None:
        """The isolation arms children by putting the tripwire folder first on PYTHONPATH."""
        self.assertEqual(os.environ['PYTHONPATH'].split(os.pathsep)[0], isolation.CHILD_TRIPWIRE)

    def test_a_python_child_is_refused_the_live_budget_root(self) -> None:
        """A read-only probe of a name that does not exist under the live authority is refused before the call."""
        probe = paths.LIVE_BUDGET_ROOT / 'p0-child-probe-does-not-exist'
        result = self.child(f'open({str(probe)!r})')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('live-state child tripwire', result.stderr)
        self.assertIn('LiveStateChildTouched', result.stderr)

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
