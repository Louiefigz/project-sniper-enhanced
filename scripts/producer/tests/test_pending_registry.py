"""Every owned expected failure names its owner and reason (MASTER-PLAN X38; P0 Step 6.0).

The test imports every test module that uses ``_pending`` (found by a static scan of ``tests/``), so each
``@pending`` decorator runs and registers itself, and then checks the registry: every entry names an owner in
``OWNERS`` and a reason, and every decorator the scan finds is registered. ``pending`` itself refuses an unknown
owner or an empty reason.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import ast
import importlib
import unittest
from pathlib import Path

import _pending

TESTS = Path(__file__).resolve().parent


def decorated() -> dict[str, list[str]]:
    """Module name -> the qualified test names that carry a ``pending(...)`` decorator (static scan)."""
    found: dict[str, list[str]] = {}
    for path in sorted(TESTS.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        if 'pending(' not in text or path.name == '_pending.py':
            continue
        for cls in [node for node in ast.parse(text).body if isinstance(node, ast.ClassDef)]:
            methods = [node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            names = [f'{path.stem}.{cls.name}.{node.name}' for node in methods
                     if any(getattr(getattr(d, 'func', None), 'id', None) == 'pending' for d in node.decorator_list)]
            found.setdefault(path.stem, []).extend(names)
    return {module: names for module, names in found.items() if names}


class PendingRegistryTests(unittest.TestCase):
    """The registry is complete and every entry is owned."""

    def test_every_pending_test_names_an_owner_and_reason(self) -> None:
        """Import each module that uses the marker; every scanned decorator is registered with an owner and reason."""
        scanned = decorated()
        for module in scanned:
            importlib.import_module(module)
        registered = {name for name in _pending.PENDING if name.split('.', 1)[0] in scanned}
        self.assertEqual(registered, {name for names in scanned.values() for name in names})
        for name, (owner, reason) in _pending.PENDING.items():
            self.assertIn(owner, _pending.OWNERS, name)
            self.assertTrue(reason.strip(), name)

    def test_unknown_owner_or_empty_reason_is_refused(self) -> None:
        """P0 is not an owner, and a marker without a reason is refused."""
        for owner, reason in (('P0', 'x'), ('P4', ''), ('P4', '   '), ('p4', 'x')):
            with self.subTest(owner=owner, reason=reason), self.assertRaises(ValueError):
                _pending.pending(owner, reason)


if __name__ == '__main__':
    unittest.main()
