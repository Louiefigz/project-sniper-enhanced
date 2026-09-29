"""Live-state tripwire for Python child processes started by tests (TEST harness only).

T0's audit hook (``_live_state_isolation``) guards the test process itself; a child process never inherits it.
``_live_state_children.arm`` puts this folder first on the ``PYTHONPATH`` that children inherit, so every Python
child that keeps that variable loads this module at start-up. The parent also passes what counts as live:
``SNIPER_TEST_CHILD_REFUSED`` (JSON: the refused path prefixes and audit-event tables from ``_live_state_paths``)
and ``SNIPER_TEST_CHILD_REPORTS`` (a directory the parent checks after each test and at the end of its run).

This module imports only the standard library, adds nothing to ``sys.path`` and runs no engine code, so a child
runs exactly the code its own path selects. It only **refuses**, never redirects: an open, listing or write under
the operator's live budget authority, pool record or pool namespace, or a write anywhere under
``~/.project-sniper``, prints ``live-state child tripwire: ...`` to stderr, writes one ``*.report`` file into the
reports directory and ends the process with ``os._exit(97)`` before the system call. No ``except`` can absorb it,
and the parent fails the run from the report file even when the child's exit status is ignored. A missing or
malformed variable also exits 97 (fail closed). The interpreter's own ``sitecustomize`` (Homebrew's) is chained
after installation. Not covered: a child started with ``-I`` or ``-S``, or whose environment drops
``PYTHONPATH``, never loads this file (p0-records/live-root-readers.md). Nothing in the product imports it.

The path matching mirrors ``_live_state_paths`` (``test_live_state_child_tripwire`` checks that both refuse the
same spellings). Loaded under any other module name (that test does), nothing is installed.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys

CONFIG, REPORTS = 'SNIPER_TEST_CHILD_REFUSED', 'SNIPER_TEST_CHILD_REPORTS'
REFUSED_EXIT = 97
DATA_VOLUME = '/system/volumes/data'
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
HERE = os.path.dirname(os.path.abspath(__file__))


class TripwireConfigError(ValueError):
    """The parent's variables are missing or malformed; the child must not run."""


def canonical(path: str) -> str:
    """Normalized, case-folded spelling without a leading ``//`` or the Data-volume firmlink."""
    path = os.path.normpath(path)
    if path.startswith('//'):
        path = '/' + path.lstrip('/')
    folded = path.casefold()
    if folded == DATA_VOLUME or folded.startswith(DATA_VOLUME + '/'):
        folded = folded[len(DATA_VOLUME):] or '/'
    return folded


def descriptor_path(descriptor: object) -> str | None:
    """The path an open descriptor names (macOS F_GETPATH), or None when it cannot be read."""
    if type(descriptor) is not int or descriptor < 0 or not hasattr(fcntl, 'F_GETPATH'):
        return None
    try:
        raw = fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytes(1024))
    except OSError:
        return None
    return os.fsdecode(raw.split(b'\0', 1)[0]) or None


def absolute(value: object, directory: object) -> str | None:
    """An absolute path for a path-like or descriptor argument, resolved against its directory."""
    if type(value) is int:
        return descriptor_path(value)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if not isinstance(value, str) or not value:
        return None
    if os.path.isabs(value):
        return value
    base = descriptor_path(directory) if type(directory) is int and directory >= 0 else None
    try:
        return os.path.join(base or os.getcwd(), value)
    except OSError:
        return None


def under(path: str, prefixes: tuple[str, ...]) -> bool:
    """Whether ``path`` is one of ``prefixes`` or lies inside one."""
    return any(path == prefix or path.startswith(prefix + '/') for prefix in prefixes)


def _prefixes(value: object) -> tuple[str, ...]:
    """A non-empty list of absolute, already canonical prefixes."""
    if not isinstance(value, list) or not value:
        raise TripwireConfigError('a prefix list is missing or empty')
    if not all(isinstance(item, str) and item.startswith('/') and canonical(item) == item for item in value):
        raise TripwireConfigError('a prefix is not an absolute canonical path')
    return tuple(value)


def _positions(value: object) -> dict:
    """``{event: [argument positions]}`` with non-negative integer positions."""
    if not isinstance(value, dict) or not value:
        raise TripwireConfigError('pathEvents is missing or empty')
    rows = {event: positions for event, positions in value.items() if isinstance(event, str)
            and isinstance(positions, list) and all(type(item) is int and item >= 0 for item in positions)}
    if len(rows) != len(value):
        raise TripwireConfigError('pathEvents has a malformed row')
    return {event: tuple(positions) for event, positions in rows.items()}


def _descriptors(value: object) -> dict:
    """``{event: {path position: descriptor position}}``; JSON keys arrive as strings."""
    if not isinstance(value, dict):
        raise TripwireConfigError('dirFds is missing')
    try:
        return {event: {int(path): int(fd) for path, fd in rows.items()} for event, rows in value.items()}
    except (AttributeError, TypeError, ValueError) as error:
        raise TripwireConfigError('dirFds has a malformed row') from error


def load_config(text: str | None) -> dict:
    """The parent's JSON value, validated; TripwireConfigError when anything is missing or malformed."""
    if not text:
        raise TripwireConfigError(f'{CONFIG} is missing')
    try:
        value = json.loads(text)
    except ValueError as error:
        raise TripwireConfigError(f'{CONFIG} is not JSON') from error
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise TripwireConfigError(f'{CONFIG} is not a schema-1 object')
    reads = value.get('readEvents')
    if not isinstance(reads, list) or not all(isinstance(item, str) for item in reads):
        raise TripwireConfigError('readEvents is missing or malformed')
    return {'refused': _prefixes(value.get('refused')), 'writeRefused': _prefixes(value.get('writeRefused')),
            'pathEvents': _positions(value.get('pathEvents')), 'dirFds': _descriptors(value.get('dirFds')),
            'readEvents': frozenset(reads)}


class Tripwire:
    """The refusing audit hook: matching as ``_live_state_paths.refused_path``, then report and exit 97."""

    def __init__(self, config: dict, reports: str) -> None:
        """Keep the validated tables and the reports directory; nothing is refused yet."""
        self.config, self.reports, self.refusing = config, reports, False

    def event_paths(self, event: str, args: tuple) -> list[str]:
        """Every canonical path an audit event names."""
        fds, rows = self.config['dirFds'].get(event, {}), []
        for position in self.config['pathEvents'].get(event, ()):
            if position >= len(args):
                continue
            directory = args[fds[position]] if position in fds and fds[position] < len(args) else None
            path = absolute(args[position], directory)
            rows += [canonical(path)] if path is not None else []
        return rows

    def mutates(self, event: str, args: tuple) -> bool:
        """Whether a path event can change the file system (opens are judged by their flags)."""
        if event == 'open':
            return not isinstance(args[2] if len(args) > 2 else None, int) or bool(args[2] & WRITE_FLAGS)
        return event not in self.config['readEvents']

    def refused(self, event: str, args: tuple) -> str | None:
        """The live path this audit event would touch in a refused way, else None."""
        for path in self.event_paths(event, args):
            if under(path, self.config['refused']) or (under(path, self.config['writeRefused'])
                                                       and self.mutates(event, args)):
                return path
        return None

    def __call__(self, event: str, args: tuple) -> None:
        """Audit hook: a refused event is reported and ends the process before the system call."""
        if self.refusing or event not in self.config['pathEvents']:
            return
        path = self.refused(event, args)
        if path is None:
            return
        self.refusing = True  # the report's own open() re-enters this hook
        self.report(f'live-state child tripwire: {event} {path} (pid {os.getpid()})')
        os._exit(REFUSED_EXIT)

    def report(self, line: str) -> None:
        """One stderr line and one report file for the parent; a failure to write does not stop the exit."""
        try:
            sys.stderr.write(line + '\n')
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        name = os.path.join(self.reports, f'{os.getpid()}-{os.urandom(6).hex()}.report')
        try:
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, (line + '\n').encode('utf-8', 'surrogateescape'))
            os.close(descriptor)
        except OSError:
            pass


def reports_directory(text: str | None, tripwire: Tripwire) -> str:
    """The parent's reports directory: absolute, existing and not itself refused."""
    if not text or not os.path.isabs(text) or not os.path.isdir(text):
        raise TripwireConfigError(f'{REPORTS} is not an existing absolute directory')
    if tripwire.refused('open', (os.path.join(text, 'probe.report'), 'w', os.O_WRONLY | os.O_CREAT)):
        raise TripwireConfigError(f'{REPORTS} lies under a refused prefix')
    return text


def install() -> None:
    """Validate the parent's variables and add the refusing audit hook."""
    tripwire = Tripwire(load_config(os.environ.get(CONFIG)), '')
    tripwire.reports = reports_directory(os.environ.get(REPORTS), tripwire)
    sys.addaudithook(tripwire)


def chain() -> None:
    """Run the next ``sitecustomize`` on sys.path (the interpreter's own), as the site module would have."""
    import importlib.machinery
    import importlib.util
    later = [entry for entry in sys.path if os.path.abspath(entry or '.') != HERE]
    spec = importlib.machinery.PathFinder.find_spec('sitecustomize', later)
    if spec is None or spec.origin is None or os.path.dirname(os.path.abspath(spec.origin)) == HERE:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


if __name__ == 'sitecustomize':
    try:
        install()
    except Exception as error:  # fail closed: a child without the tripwire must not run
        sys.stderr.write(f'live-state child tripwire could not install: {type(error).__name__}: {error}\n')
        sys.stderr.flush()
        os._exit(REFUSED_EXIT)
    chain()
