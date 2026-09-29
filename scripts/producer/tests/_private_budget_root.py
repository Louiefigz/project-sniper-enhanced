"""Rebinding the engine's root functions, and a private budget root for supervised media scripts.

``rebind`` replaces an engine function and every loaded module attribute that holds that
exact function object, whatever name it was imported under. _live_state_isolation uses it for
the test process.

``use_private_budget_root`` is for the supervised real-media scripts in tests/ (the
``*_integration.py`` scripts, native_perf_fixture.py and native_route_canary_fixture.py), which
each call it first thing in ``__main__``. They get a private production-budget authority, so a
live batch never refuses or charges them. They keep the real host pool namespace and pool record,
because real renders must share the host's heavy-slot limit with every other owner on this Mac.
Nothing here installs the test isolation's audit hook.
"""
from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

from studio import native_budget_store


def rebind(owner: object, name: str, replacement: object) -> bool:
    """Replace ``owner.name`` everywhere it is bound, when it is still the engine's own function.

    A root a process already chose for itself (a child driver that assigned its own TEST
    namespace before importing a fixture) is kept. Returns whether anything was replaced.
    """
    original = getattr(owner, name)
    if getattr(original, '__module__', None) != owner.__name__:
        return False
    for module in list(sys.modules.values()):
        namespace = getattr(module, '__dict__', None)
        if not isinstance(namespace, dict):
            continue
        for key in [key for key, value in list(namespace.items()) if value is original]:
            namespace[key] = replacement
    return True


class _LazyRoot:
    """A private authority root created on first use and removed at exit."""

    def __init__(self) -> None:
        """Nothing is created until an owner asks for the root."""
        self.base: Path | None = None

    def __call__(self) -> Path:
        """Replacement for ``native_budget_store.default_root``."""
        if self.base is None:
            self.base = Path(tempfile.mkdtemp(prefix='sniper-supervised-budget-')).resolve()
            atexit.register(shutil.rmtree, self.base, True)
        return self.base / 'production-budgets'


def use_private_budget_root() -> None:
    """Give this supervised script a private budget authority; the pool stays the host's."""
    rebind(native_budget_store, 'default_root', _LazyRoot())
