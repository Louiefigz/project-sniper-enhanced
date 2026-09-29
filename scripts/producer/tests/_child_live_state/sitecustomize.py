"""Live-state tripwire for Python child processes started by tests (TEST harness only).

T0's audit hook (``_live_state_isolation``) guards the test process itself; a child process never inherits it.
``_live_state_isolation._install`` puts this folder first on the ``PYTHONPATH`` that children inherit, so every
Python child that keeps that variable loads this module at start-up. It only **refuses**, it never redirects:
an open, listing or write under the operator's live budget authority, pool record or pool namespace raises
``LiveStateChildTouched`` before the system call and prints ``live-state child tripwire: ...`` to stderr. A child
that was given its own private roots never reaches those paths and is unaffected.

The live paths come from ``_live_state_paths``, loaded under a private module name so a child that imports the
isolation over decoy roots (``fixtures/live_state_probe.py``) still gets its own copy. A child started with a
closed environment (``NativeRun`` workers; tests that replace ``PYTHONPATH``) does not load this file; those are
covered by the reviewed allowlist and ``p0-records/live-root-readers.md``. If the tripwire cannot be installed the
child exits with status 97 (fail closed). The interpreter's own ``sitecustomize`` (Homebrew's) is chained after
installation. Nothing in the product imports or reads this file.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
PRODUCER = os.path.dirname(TESTS)


class LiveStateChildTouched(BaseException):
    """A child process started by a test reached the operator's live per-user state."""


def _paths_module() -> object:
    """``_live_state_paths`` under a private name (never registered as ``_live_state_paths``)."""
    spec = importlib.util.spec_from_file_location('_child_tripwire_paths', os.path.join(TESTS, '_live_state_paths.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install() -> None:
    """Append the engine folders (never shadowing), load the live paths, add the refusing audit hook."""
    for folder in (TESTS, PRODUCER):
        if folder not in sys.path:
            sys.path.append(folder)
    paths = _paths_module()
    refused_path, events = paths.refused_path, paths.PATH_EVENTS

    def refuse(event: str, args: tuple) -> None:
        """Refuse a live-state operation before the system call."""
        if event not in events:
            return
        path = refused_path(event, args)
        if path is not None:
            sys.stderr.write(f'live-state child tripwire: {event} {path} (pid {os.getpid()})\n')
            sys.stderr.flush()
            raise LiveStateChildTouched(f'child process reached live per-user state: {event} {path}')
    sys.addaudithook(refuse)


def _chain() -> None:
    """Run the next ``sitecustomize`` on sys.path (the interpreter's own), as the site module would have."""
    later = [entry for entry in sys.path if os.path.abspath(entry or '.') != HERE]
    spec = importlib.machinery.PathFinder.find_spec('sitecustomize', later)
    if spec is None or spec.origin is None or os.path.dirname(os.path.abspath(spec.origin)) == HERE:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


try:
    _install()
except Exception as error:  # fail closed: a child without the tripwire must not run
    sys.stderr.write(f'live-state child tripwire could not install: {type(error).__name__}: {error}\n')
    sys.stderr.flush()
    os._exit(97)
_chain()
