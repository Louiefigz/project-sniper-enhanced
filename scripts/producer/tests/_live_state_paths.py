"""Which audit events would touch the operator's live per-user state (used by _live_state_isolation).

Refused on any access: the budget authority (``~/.project-sniper/production-budgets``), the
host pool qualification record (``~/.project-sniper/native-pool``) and the host-wide pool
namespace. Refused on a write: anything else under ``~/.project-sniper`` (installed runtimes
stay readable, because retained-evidence tests hash their tools).

Paths are compared case-folded (APFS is case-insensitive) after normalization, a leading
``//`` and the ``/System/Volumes/Data`` firmlink prefix are removed, and the /tmp and /var
spellings of /private match. A relative path whose event carries a directory descriptor, and a
path given as a descriptor, are resolved with ``fcntl(F_GETPATH)``. The live spellings are
built from the resolved account home and pool parent, so the live folders themselves are
never stat'ed.

Not caught: stat/exists/access (not audit events); ``os.open(..., dir_fd=)`` and ``open`` with
an ``opener`` (the audit event carries no directory descriptor, so a relative name is judged
against the working directory); a path through a symlink the test itself made; sqlite
``file:`` URIs; ``importlib.reload`` of an engine module, which restores the real root
functions; and anything a child process does.
"""
from __future__ import annotations

import fcntl
import os
import pwd
from collections.abc import Iterator
from pathlib import Path

import native_work_lease

ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
ACCOUNT_STATE = ACCOUNT_HOME / '.project-sniper'
LIVE_BUDGET_ROOT = ACCOUNT_STATE / 'production-budgets'
LIVE_POOL_RECORDS = ACCOUNT_STATE / 'native-pool'
LIVE_POOL_ROOT = native_work_lease.default_state_root()
DATA_VOLUME = '/system/volumes/data'
PRIVATE_ALIASES = ('/private/tmp/', '/private/var/', '/private/etc/')
# Audit events whose listed argument positions are file-system paths.
PATH_EVENTS = {
    **dict.fromkeys(('open', 'os.remove', 'os.mkdir', 'os.listdir', 'os.scandir', 'os.chmod',
                     'os.chown', 'os.utime', 'os.truncate', 'os.rmdir', 'os.walk', 'os.fwalk',
                     'os.chflags', 'os.lchflags', 'os.lchmod', 'os.mkfifo', 'os.mknod', 'os.chdir',
                     'os.listxattr', 'os.getxattr', 'os.setxattr', 'os.removexattr', 'glob.glob',
                     'pathlib.Path.glob', 'pathlib.Path.rglob', 'shutil.rmtree', 'shutil.chown',
                     'shutil.copystat', 'shutil.copymode', 'tempfile.mkdtemp', 'tempfile.mkstemp',
                     'sqlite3.connect'), (0,)),
    **dict.fromkeys(('os.rename', 'os.link', 'os.symlink', 'shutil.copyfile', 'shutil.copytree',
                     'shutil.move'), (0, 1)),
    'glob.glob/2': (0, 2),
}
# For events that carry them: path position -> position of that path's directory descriptor.
DIR_FDS = {'os.mkdir': {0: 2}, 'os.remove': {0: 1}, 'os.rmdir': {0: 1}, 'os.chmod': {0: 2},
           'os.chown': {0: 3}, 'os.utime': {0: 3}, 'os.mkfifo': {0: 2}, 'os.mknod': {0: 3},
           'os.rename': {0: 2, 1: 3}, 'os.link': {0: 2, 1: 3}, 'os.symlink': {1: 2},
           'shutil.rmtree': {0: 1}, 'glob.glob/2': {0: 3}}
# Path events that only read; every other path event (and an open with write flags) mutates.
READ_EVENTS = frozenset({'os.listdir', 'os.scandir', 'os.walk', 'os.fwalk', 'os.chdir', 'os.listxattr',
                         'os.getxattr', 'glob.glob', 'glob.glob/2', 'pathlib.Path.glob', 'pathlib.Path.rglob'})
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def canonical(path: str) -> str:
    """Normalized, case-folded spelling without a leading ``//`` or the Data-volume firmlink."""
    path = os.path.normpath(path)
    if path.startswith('//'):
        path = '/' + path.lstrip('/')
    folded = path.casefold()
    if folded == DATA_VOLUME or folded.startswith(DATA_VOLUME + '/'):
        folded = folded[len(DATA_VOLUME):] or '/'
    return folded


def _spellings(parent: Path, *leaf: str) -> set[str]:
    """Spellings of parent/leaf from the literal and the resolved parent; the leaf is never stat'ed."""
    names = {os.path.join(str(parent), *leaf), os.path.join(os.path.realpath(parent), *leaf)}
    names.update(name.removeprefix('/private') for name in list(names) if name.startswith(PRIVATE_ALIASES))
    return {canonical(name) for name in names}


REFUSED_PREFIXES = tuple(sorted(_spellings(ACCOUNT_HOME, '.project-sniper', 'production-budgets')
                                | _spellings(ACCOUNT_HOME, '.project-sniper', 'native-pool')
                                | _spellings(LIVE_POOL_ROOT.parent, LIVE_POOL_ROOT.name)))
WRITE_REFUSED_PREFIXES = tuple(sorted(_spellings(ACCOUNT_HOME, '.project-sniper')))


def descriptor_path(descriptor: object) -> str | None:
    """The path an open descriptor names (macOS F_GETPATH), or None when it cannot be read."""
    if type(descriptor) is not int or descriptor < 0 or not hasattr(fcntl, 'F_GETPATH'):
        return None
    try:
        raw = fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytes(1024))
    except OSError:
        return None
    return os.fsdecode(raw.split(b'\0', 1)[0]) or None


def _absolute(value: object, directory: object) -> str | None:
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


def event_paths(event: str, args: tuple) -> Iterator[str]:
    """Every canonical path an audit event names."""
    fds = DIR_FDS.get(event, {})
    for position in PATH_EVENTS.get(event, ()):
        if position >= len(args):
            continue
        directory = args[fds[position]] if position in fds and fds[position] < len(args) else None
        path = _absolute(args[position], directory)
        if path is not None:
            yield canonical(path)


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    """Whether ``path`` is one of ``prefixes`` or lies inside one."""
    return any(path == prefix or path.startswith(prefix + '/') for prefix in prefixes)


def _mutates(event: str, args: tuple) -> bool:
    """Whether a path event can change the file system (opens are judged by their flags)."""
    if event == 'open':
        return not isinstance(args[2] if len(args) > 2 else None, int) or bool(args[2] & WRITE_FLAGS)
    return event not in READ_EVENTS


def refused_path(event: str, args: tuple) -> str | None:
    """The live path this audit event would touch in a refused way, else None."""
    for path in event_paths(event, args):
        if _under(path, REFUSED_PREFIXES) or (_under(path, WRITE_REFUSED_PREFIXES) and _mutates(event, args)):
            return path
    return None
