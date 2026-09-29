"""TEST probe: the live-state isolation outside test methods, in a fresh process over DECOY state.

Usage: live_state_probe.py <case> <decoy-dir>. The isolation is imported with a decoy account
home and a decoy pool namespace under <decoy-dir>, so every "live" touch lands on decoy folders;
a second hook refuses the operator's real budget authority, pool record and pool namespace, so
a broken probe exits with status 3 before touching them. Prints one JSON line.

Cases: shared (class fixtures ask for a root), swallow (a class fixture catches a refusal),
propagate (a class fixture's refusal propagates; a later class must still run), reload
(the isolation is reloaded during a test), twice (imported under a second module name) and
import-touch (a swallowed touch outside any run; the process must exit with status 1).
"""
from __future__ import annotations

import importlib
import io
import json
import os
import pwd
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[2])]
CASE, DECOY = sys.argv[1], Path(sys.argv[2]).resolve()
_REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir.casefold()
_REAL = (_REAL_HOME + '/.project-sniper/production-budgets', _REAL_HOME + '/.project-sniper/native-pool',
         f'/sniper-native-work-{os.geteuid()}')


def _real_guard(event: str, args: tuple) -> None:
    """Stop the probe (status 3) before any argument names the operator's real live state.

    One exception: the isolation sets ``SNIPER_TEST_CHILD_REFUSED`` to the refused live prefixes for its children;
    setting that one variable touches nothing (reviews/CS1-REVIEW.md F1, C1FIX-REVIEW.md n1).
    """
    if event == 'os.putenv' and args and os.fsdecode(args[0]) == 'SNIPER_TEST_CHILD_REFUSED':
        return
    for value in args:
        if isinstance(value, (str, bytes, os.PathLike)) and any(
                needle in os.fsdecode(os.fspath(value)).casefold() for needle in _REAL):
            os._exit(3)


sys.addaudithook(_real_guard)
HOME, POOL = DECOY / 'home', DECOY / 'pool' / 'sniper-native-work-decoy'
(HOME / '.project-sniper' / 'production-budgets').mkdir(parents=True)
POOL.mkdir(parents=True)
import native_work_lease  # noqa: E402
native_work_lease.default_state_root = lambda: POOL
_getpwuid = pwd.getpwuid
pwd.getpwuid = lambda _uid: SimpleNamespace(pw_dir=str(HOME))
import _live_state_isolation as iso  # noqa: E402
pwd.getpwuid = _getpwuid
from studio import native_budget_store  # noqa: E402

SEEN: dict[str, object] = {}


class FixtureRoot(unittest.TestCase):
    """A class fixture that asks for a private root."""

    @classmethod
    def setUpClass(cls) -> None:
        """Class fixtures get no shared root."""
        SEEN['fixtureRoot'] = str(native_budget_store.default_root())

    def test_skipped_with_its_class(self) -> None:
        """Never runs when the fixture fails."""


class SwallowedTouch(unittest.TestCase):
    """A class fixture that catches the refusal."""

    @classmethod
    def setUpClass(cls) -> None:
        """Touch the decoy authority and hide the error."""
        try:
            os.listdir(iso.LIVE_BUDGET_ROOT)
        except Exception:  # noqa: BLE001 - the probe swallows it on purpose
            pass

    def test_runs(self) -> None:
        """Passes; the run must still fail."""


class PropagatedTouch(unittest.TestCase):
    """A class fixture whose refusal propagates."""

    @classmethod
    def setUpClass(cls) -> None:
        """Touch the decoy authority."""
        os.listdir(iso.LIVE_BUDGET_ROOT)

    def test_never_runs(self) -> None:
        """Skipped with its class."""


class Later(unittest.TestCase):
    """A class after the failing fixture."""

    def test_later(self) -> None:
        """Must still run."""
        SEEN['laterRan'] = True


class Reload(unittest.TestCase):
    """Reloading the isolation module keeps the installed state."""

    def test_1_reload(self) -> None:
        """Re-execute the module."""
        importlib.reload(iso)

    def test_2_after_reload(self) -> None:
        """Roots are still private and per test."""
        SEEN['afterReload'] = str(native_budget_store.default_root())


def run(*classes: type) -> dict:
    """Run classes with a real TextTestRunner and summarize the result."""
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in classes)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return {'ok': result.wasSuccessful(), 'testsRun': result.testsRun,
            'errors': [[case.id(), text.strip().splitlines()[-1]] for case, text in result.errors]}


def twice() -> dict:
    """Import the isolation under a second name and compare its state."""
    second = importlib.import_module('tests._live_state_isolation')
    return {'distinctModule': second is not iso, 'sharedState': second.STATE is iso.STATE,
            'originalIsEngine': second.ORIGINAL_DEFAULT_ROOT.__module__ == 'studio.native_budget_store',
            'wrapperInstalled': getattr(unittest.TestCase.run, 'live_state', None) is iso.STATE}


def import_touch() -> dict:
    """A touch outside any run, swallowed; only the exit check can report it."""
    try:
        os.listdir(iso.LIVE_BUDGET_ROOT)
    except Exception:  # noqa: BLE001 - the probe swallows it on purpose
        pass
    return {'swallowed': True}


CASES = {'shared': lambda: run(FixtureRoot, Later), 'swallow': lambda: run(SwallowedTouch),
         'propagate': lambda: run(PropagatedTouch, Later), 'reload': lambda: run(Reload),
         'twice': twice, 'import-touch': import_touch}
print(json.dumps({**CASES[CASE](), 'seen': SEEN, 'decoyBudget': str(iso.LIVE_BUDGET_ROOT)}), flush=True)
