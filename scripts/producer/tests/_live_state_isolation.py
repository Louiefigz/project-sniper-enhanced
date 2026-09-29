"""Private production-budget and native-pool roots for every test; the live ones are refused.

Importing this module replaces ``native_budget_store.default_root`` and
``native_work_lease.state_root`` for the whole process, including every loaded module attribute
that holds either function under any name. Each test method gets fresh private roots, created
on first use and removed after it. With a private pool namespace,
``native_work_qualification.record_directory()`` returns None, so the operator's host
qualification record is never read either.

Class and module fixtures get no shared root. While a test run is active, calling either
root outside a test method raises ``LiveStateScopeError``. unittest reports that as an error
for the class or module, and the rest of the run continues. Outside a run (at import time),
one process root is used.

``_common``, ``_budget_fixture``, the native/pool fixtures and ``selftest.py`` import this
module, and so must every test module whose imports can reach those owners.
test_live_state_isolation.py enforces that.

An audit hook refuses a touch of live state before the system call (_live_state_paths.py
lists what counts as live and what cannot be seen). Inside a test method it raises
``LiveStateTouched``, a BaseException that engine ``except Exception`` handling cannot absorb.
If the test swallows it anyway, the test is still reported as an error. Outside a test method
it raises ``LiveStateFixtureTouched``, an ordinary exception, so unittest turns it into a
class- or module-level error instead of aborting the run.

Every refusal or scope misuse outside a test method is also held until the end of the run.
If the error for it was swallowed, ``stopTestRun`` reports it as an error. If no runner ever
reported it, the process exits with status 1. Re-importing or reloading this module keeps
the installed state.

Python children are armed with the child tripwire (``_live_state_children``). A child refused a live
path writes a report file and exits 97; each report fails the test that was running when the check ran
(after every test method) or, later, the run itself, even when the child's exit status was ignored.
"""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

import _live_state_children as children
import _live_state_paths
import native_work_lease
from _live_state_paths import (ACCOUNT_STATE, LIVE_BUDGET_ROOT, LIVE_POOL_RECORDS, LIVE_POOL_ROOT,
                               PATH_EVENTS, refused_path)
from _private_budget_root import rebind
from studio import native_budget_store

__all__ = ['ACCOUNT_STATE', 'LIVE_BUDGET_ROOT', 'LIVE_POOL_RECORDS', 'LIVE_POOL_ROOT', 'refused_path']


class LiveStateTouched(BaseException):
    """A test method reached the operator's live per-user state; never absorbed as an ordinary error."""


class LiveStateFixtureTouched(Exception):
    """A class or module fixture (or import-time code) reached live state; unittest reports it."""


class LiveStateScopeError(Exception):
    """A private root was requested outside a test method while a test run is active."""


@dataclass
class _Scope:
    """Private roots for one test method (``test`` set) or for the process, created on first use."""

    label: str
    test: unittest.TestCase | None = None
    directory: tempfile.TemporaryDirectory | None = None
    touches: list[str] = field(default_factory=list)

    def base(self) -> Path:
        """This scope's private directory, created on first use."""
        if self.directory is None:
            self.directory = tempfile.TemporaryDirectory(prefix='sniper-test-state-')
        return Path(self.directory.name).resolve()

    def close(self) -> None:
        """Remove whatever this scope's owners wrote."""
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None


@dataclass
class _State:
    """Everything installed once per process, shared by every copy of this module."""

    scopes: list[_Scope]
    originals: dict[str, object]
    runs: list[int] = field(default_factory=list)
    unreported: list[str] = field(default_factory=list)


class _RunCheck:
    """Stands in for a test when the end-of-run check reports what happened outside tests."""

    failureException = AssertionError

    def id(self) -> str:
        """The label unittest prints for this error."""
        return 'live-state isolation (outside test methods)'

    def shortDescription(self) -> None:
        """No docstring line."""
        return None

    def __str__(self) -> str:
        """Same as the id."""
        return self.id()


_INSTALLED = getattr(unittest.TestCase.run, 'live_state', None)
STATE: _State = _INSTALLED or _State([_Scope('process')], {
    'default_root': native_budget_store.default_root, 'state_root': native_work_lease.state_root,
    'run': unittest.TestCase.run, 'start': unittest.TestResult.startTestRun,
    'stop': unittest.TestResult.stopTestRun})
_SCOPES = STATE.scopes


def _current(owner: str) -> _Scope:
    """The scope a root belongs to; outside a test method during a run there is none."""
    scope = STATE.scopes[-1]
    if scope.test is None and STATE.runs:
        message = (f'{owner} was called outside a test method while tests run (a class or module '
                   'fixture); fixtures get no shared private root, so create one and patch it yourself')
        STATE.unreported.append(message)
        raise LiveStateScopeError(message)
    return scope


def isolated_budget_root() -> Path:
    """Replacement for ``native_budget_store.default_root``: the current test's authority root."""
    return _current('native_budget_store.default_root()').base() / 'production-budgets'


def isolated_state_root() -> Path:
    """Replacement for ``native_work_lease.state_root``: the current test's pool namespace."""
    return _current('native_work_lease.state_root()').base() / 'native-work'


def _audit(event: str, args: tuple) -> None:
    """Refuse an operation on live state before the system call happens."""
    if event not in PATH_EVENTS:
        return
    path = refused_path(event, args)
    if path is None:
        return
    scope = STATE.scopes[-1]
    message = f'{scope.label} reached live per-user state: {event} {path}'
    scope.touches.append(message)
    if scope.test is not None:
        raise LiveStateTouched(message)
    STATE.unreported.append(message)
    raise LiveStateFixtureTouched(message)


def _reported(result: object, prefix: str = '') -> str:
    """Every error and failure text already in ``result`` for tests whose id starts with ``prefix``."""
    rows = getattr(result, 'errors', []) + getattr(result, 'failures', [])
    return '\n'.join(text for case, text in rows if case.id().startswith(prefix))


def _report_swallowed(test: unittest.TestCase, scope: _Scope, result: object) -> None:
    """Fail a test whose live-state refusal was caught instead of propagating."""
    if not scope.touches or result is None or LiveStateTouched.__name__ in _reported(result, test.id()):
        return
    error = LiveStateTouched(f'{test.id()} reached live per-user state and swallowed the refusal: '
                             + '; '.join(scope.touches))
    result.addError(test, (LiveStateTouched, error, None))


def _run_with_private_roots(test: unittest.TestCase,
                            result: unittest.TestResult | None = None) -> unittest.TestResult | None:
    """Run one test with fresh private roots, then remove them."""
    scope = _Scope(test.id(), test)
    STATE.scopes.append(scope)
    children.set_current(test.id())
    try:
        outcome = STATE.originals['run'](test, result)
    finally:
        children.set_current('outside test methods')
        STATE.scopes.remove(scope)
        scope.close()
    _report_swallowed(test, scope, outcome)
    _report_children(test, outcome)
    return outcome


def _report_children(test: object, result: object) -> None:
    """Fail ``test`` (or the run) for every child refusal report not reported yet."""
    lines = children.new_reports()
    if lines and result is not None:
        error = LiveStateTouched('a child process was refused live per-user state: ' + '; '.join(lines))
        result.addError(test, (LiveStateTouched, error, None))


def _start_test_run(result: unittest.TestResult) -> None:
    """Mark the start of a run; roots now belong to test methods only."""
    STATE.runs.append(len(STATE.unreported))
    STATE.originals['start'](result)


def _stop_test_run(result: unittest.TestResult) -> None:
    """Report this run's touches and scope misuse outside test methods that nothing reported."""
    start = STATE.runs.pop() if STATE.runs else 0
    fresh, STATE.unreported[start:] = STATE.unreported[start:], []
    reported = _reported(result)
    missing = [message for message in fresh if message not in reported]
    if missing:
        error = LiveStateTouched('outside test methods: ' + '; '.join(missing))
        result.addError(_RunCheck(), (LiveStateTouched, error, None))
    _report_children(_RunCheck(), result)
    STATE.originals['stop'](result)


def _exit_check() -> None:
    """Fail the process when a touch outside test methods was never reported by a runner."""
    STATE.scopes[0].close()
    STATE.unreported.extend(children.new_reports())
    children.remove_own_directory()
    if not STATE.unreported:
        return
    sys.stdout.flush()
    sys.stderr.write('live-state isolation: unreported touches outside test methods: '
                     + '; '.join(STATE.unreported) + '\n')
    sys.stderr.flush()
    os._exit(1)


CHILD_TRIPWIRE = children.CHILD_TRIPWIRE


def _install() -> None:
    """Patch the roots, wrap test runs and runs, add the audit hook and arm the child tripwire, once per process."""
    children.arm(_live_state_paths)
    if _INSTALLED is not None:
        return
    rebind(native_budget_store, 'default_root', isolated_budget_root)
    rebind(native_work_lease, 'state_root', isolated_state_root)
    _run_with_private_roots.live_state = STATE
    unittest.TestCase.run = _run_with_private_roots
    unittest.TestResult.startTestRun = _start_test_run
    unittest.TestResult.stopTestRun = _stop_test_run
    atexit.register(_exit_check)
    sys.addaudithook(_audit)


_install()
ORIGINAL_DEFAULT_ROOT = STATE.originals['default_root']
ORIGINAL_STATE_ROOT = STATE.originals['state_root']
