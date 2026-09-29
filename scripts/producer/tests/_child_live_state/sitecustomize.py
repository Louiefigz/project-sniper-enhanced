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
reports directory and ends the process with ``os._exit(97)`` before the system call. No ``except`` can absorb it.
The refusal is per thread: the reporting thread may only open its own report file, and any other thread that
reaches a refused path waits on a lock before its system call until the process has exited. Each report names the
test that was running when the child started (``SNIPER_TEST_CURRENT``); the parent checks the folder after each
test, at the end of its run, and the suite wrappers check it again after the process exits. A missing or
malformed variable also exits 97 (fail closed) and, when the reports folder is usable, leaves an install-failure
report. The interpreter's own ``sitecustomize`` (Homebrew's) is chained after installation. Not covered: a child
started with ``-I``, ``-S`` or ``-E``, or whose environment drops ``PYTHONPATH``; a non-Python child; a ``ctypes``
call (no audit event); ``os.mkfifo`` and ``os.mknod`` (no audit event in CPython 3.14); ``os.posix_spawn`` file
actions; an open through a symlink that already existed. The report file is written before stderr, and exit 97
follows whatever either write does. A forked child gets a fresh gate. Each arming sets ``PYTHONPYCACHEPREFIX``
to a new empty folder, so no ``__pycache__`` beside this file or in an inherited prefix is ever read.
Nothing in the product imports it.

The path matching mirrors ``_live_state_paths`` (``test_live_state_child_tripwire`` checks that both refuse the
same spellings). Loaded under any other module name (that test does), nothing is installed.
"""
from __future__ import annotations

import _thread
import fcntl
import json
import os
import sys

CONFIG, REPORTS, CURRENT = 'SNIPER_TEST_CHILD_REFUSED', 'SNIPER_TEST_CHILD_REPORTS', 'SNIPER_TEST_CURRENT'
LIVE_MARKS = ('/.project-sniper', '/sniper-native-work')  # the live roots' own names; never a reports folder
REFUSED_EXIT = 97
BIND = 'socket.bind'  # an AF_UNIX bind creates a file; the parent's tables do not list it (child-side only)
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
        self.config, self.reports = config, reports
        self.reporter, self.report_file, self.gate = None, None, _thread.allocate_lock()

    def event_paths(self, event: str, args: tuple) -> list[str]:
        """Every canonical path an audit event names (``socket.bind`` of an AF_UNIX path creates a file too)."""
        if event == BIND:
            address = args[1] if len(args) > 1 else None
            path = absolute(address, None) if isinstance(address, (str, bytes, os.PathLike)) else None
            return [canonical(path)] if path is not None else []
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
        """Audit hook: a refused event is reported and ends the process before the system call.

        Only the reporting thread re-enters, and only for its own report file; any other event of that thread
        exits at once. Every other thread that reaches a refused path blocks on the gate before its system call.
        """
        if event not in self.config['pathEvents'] and event != BIND:
            return
        if self.reporter == _thread.get_ident():
            if self.event_paths(event, args) == [canonical(self.report_file)]:
                return
            os._exit(REFUSED_EXIT)
        path = self.refused(event, args)
        if path is None:
            return
        self.gate.acquire()  # never released: the holder exits the process
        try:
            self.report_file = report_name(self.reports)
            self.reporter = _thread.get_ident()
            write_report(self.report_file, f'live-state child tripwire: {event} {path} (pid {os.getpid()}; '
                                           f'test {os.environ.get(CURRENT) or "unknown"})')
        finally:
            os._exit(REFUSED_EXIT)

    def after_fork(self) -> None:
        """A forked child gets a fresh gate: a fork during another thread's report must not inherit a held lock."""
        self.reporter, self.report_file, self.gate = None, None, _thread.allocate_lock()


def report_name(folder: str) -> str:
    """A fresh report file name in ``folder``."""
    return os.path.join(folder, f'{os.getpid()}-{os.urandom(6).hex()}.report')


def write_report(name: str, line: str) -> None:
    """The report file first, then one stderr line; nothing raised here can stop the caller's exit 97."""
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, (line + '\n').encode('utf-8', 'surrogateescape'))
        os.close(descriptor)
    except BaseException:  # noqa: B036  the caller exits 97 regardless (C1FIX-REVIEW D3)
        pass
    try:
        sys.stderr.write(line + '\n')
        sys.stderr.flush()
    except BaseException:  # noqa: B036  stderr may be None, closed, or a writer that raises
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
    os.register_at_fork(after_in_child=tripwire.after_fork)
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


def install_failed(error: Exception) -> None:
    """Fail closed: report the install failure (when the reports folder is usable) and exit 97."""
    line = (f'live-state child tripwire could not install: {type(error).__name__}: {error} '
            f'(pid {os.getpid()}; test {os.environ.get(CURRENT) or "unknown"})')
    folder = os.environ.get(REPORTS) or ''
    usable = os.path.isabs(folder) and os.path.isdir(folder) and not any(mark in canonical(folder) for mark in LIVE_MARKS)
    write_report(report_name(folder) if usable else os.devnull, line)
    os._exit(REFUSED_EXIT)


if __name__ == 'sitecustomize':
    try:
        install()
    except Exception as error:  # a child without the tripwire must not run
        install_failed(error)
    chain()
