"""The child tripwire's matcher and the in-process roots (C1-fix; reviews/CS1-REVIEW.md F1, ST-5).

``ChildMatcherParityTests`` loads the child ``sitecustomize`` under another module name (nothing is installed) and
checks that it refuses exactly the spellings ``_live_state_paths.refused_path`` refuses. ``InProcessRootTests``
checks that each owner has one module object and that late (function-level) imports bind this test's private
root. Split from ``test_live_state_child_tripwire.py`` to keep both under 300 lines.
"""
from __future__ import annotations

import _live_state_isolation as isolation
import _live_state_children as children
import _live_state_paths as paths

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
