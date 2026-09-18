#!/usr/bin/env python3
"""Advisory locks that keep Sniper's maintenance steps and its work apart.

Two lock files, both held with ``flock(2)`` so the kernel releases them when the
last holder exits — a ``kill -9`` never leaves a stale lock behind:

* ``maintenance.lock`` — EXCLUSIVE for the installer (and so ``use-provider``),
  ``uninstall`` and ``clean-caches``; SHARED for everything that uses the install
  while it runs: the app server, editor and sign-in sessions, the doctor and any
  process that resolves the render runtime (``studio.native_runtime``).
* ``runtime-build.lock`` — EXCLUSIVE while one process constructs the render
  runtime, so two renders never build it at the same time.

A holder that ``exec``s (the shell wrappers do) or forks keeps the lock: the open
file description is inherited, and ``SNIPER_LOCK_FD``/``SNIPER_LOCK_MODE`` tell a
descendant that it already holds it, so the installer's own doctor run does not
deadlock against the installer. Descriptors are verified by inode, never trusted
from the environment alone.

CLI (stdlib only; any Python 3.9+ can run it, so the installer uses it before the
app's virtual environment exists)::

    sniper_lock.py exec   --state-dir D --mode exclusive|shared --label L -- CMD...
    sniper_lock.py hold   --state-dir D --mode exclusive|shared --label L --seconds N
    sniper_lock.py status --state-dir D
"""
from __future__ import annotations

import argparse
import atexit
import errno
import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MAINTENANCE = "maintenance"
RUNTIME_BUILD = "runtime-build"
ENV_FD = "SNIPER_LOCK_FD"
ENV_MODE = "SNIPER_LOCK_MODE"
BUSY_EXIT = 75  # EX_TEMPFAIL: try again later
_MODES = {"exclusive": fcntl.LOCK_EX, "shared": fcntl.LOCK_SH}
_PROCESS_HOLD: dict[str, int] = {}


class LockBusy(RuntimeError):
    """The lock is held by another process in a conflicting mode."""


def state_dir(app_root: Path) -> Path:
    """Where the locks live: ``runtime/state`` in a package, else beside the runtime cache.

    A package is recognised by its layout (``<pkg>/app`` next to
    ``<pkg>/install/lib/common.sh``); a developer checkout has no ``runtime/``
    folder, so its locks sit in the git-ignored render-runtime cache instead.
    """
    package = app_root.parent
    if app_root.name == "app" and (package / "install/lib/common.sh").is_file():
        return package / "runtime" / "state"
    return app_root / "templates/motion/.sniper-native-runtime/.locks"


def lock_file(directory: Path, name: str) -> Path:
    """Path of one named lock file inside a state directory."""
    return directory / f"{name}.lock"


def _open(path: Path) -> int:
    """Open (creating if needed) a lock file; never truncates, never deletes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)


def inherited_mode(path: Path) -> str | None:
    """The mode this process already holds ``path`` in through an inherited descriptor."""
    raw, mode = os.environ.get(ENV_FD, ""), os.environ.get(ENV_MODE, "")
    if not raw.isdigit() or mode not in _MODES:
        return None
    try:
        held, wanted = os.fstat(int(raw)), os.stat(path)
    except OSError:
        return None
    same = (held.st_dev, held.st_ino) == (wanted.st_dev, wanted.st_ino)
    return mode if same else None


def _pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _records_dir(path: Path) -> Path:
    return path.parent / "lock-holders"


def _write_record(path: Path, mode: str, label: str) -> Path:
    """Note who holds the lock, for messages only; the flock is the authority."""
    directory = _records_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / f"{path.stem}.{os.getpid()}.json"
    record.write_text(json.dumps({"pid": os.getpid(), "mode": mode, "label": label,
                                  "since": time.strftime("%H:%M:%S")}), encoding="utf-8")
    return record


def _pids_with_file_open(path: Path) -> list[int]:
    """Every process with the lock file open, whether or not it wrote a record."""
    try:
        done = subprocess.run(["lsof", "-t", "--", str(path)], capture_output=True,
                              text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return sorted({int(p) for p in done.stdout.split() if p.isdigit()} - {os.getpid()})


def describe_holders(path: Path) -> str:
    """Human description of who holds a lock, e.g. ``installer (pid 12, since 10:02:11)``."""
    labelled: dict[int, str] = {}
    for record in sorted(_records_dir(path).glob(f"{path.stem}.*.json")):
        try:
            row = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row.get("pid"), int) and _pid_alive(row["pid"]):
            labelled[row["pid"]] = f"{row.get('label', '?')} (pid {row['pid']}, since {row.get('since', '?')})"
        else:
            record.unlink(missing_ok=True)
    for pid in _pids_with_file_open(path):
        if pid not in labelled:
            name = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True,
                                  text=True, check=False).stdout.strip()
            labelled[pid] = f"{os.path.basename(name) or 'process'} (pid {pid})"
    return ", ".join(labelled[pid] for pid in sorted(labelled)) or "another Sniper process"


def acquire(path: Path, mode: str, label: str, wait: float = 0.0) -> int:
    """Take ``path`` in ``mode``; return the descriptor that holds it.

    Args:
        path: Lock file.
        mode: ``exclusive`` or ``shared``.
        label: What the holder is doing, for other processes' messages.
        wait: Seconds to keep trying before giving up; 0 = try once.

    Raises:
        LockBusy: Another process holds it in a conflicting mode.
    """
    fd = _open(path)
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fd, _MODES[mode] | fcntl.LOCK_NB)
            break
        except OSError as error:
            if error.errno not in (errno.EWOULDBLOCK, errno.EAGAIN) or time.monotonic() >= deadline:
                os.close(fd)
                raise LockBusy(describe_holders(path)) from error
            time.sleep(0.1)
    _write_record(path, mode, label)
    return fd


def _covers(held: str | None, wanted: str) -> bool:
    return held == "exclusive" or held == wanted == "shared"


def hold_for_process(app_root: Path, label: str) -> None:
    """Hold the maintenance lock SHARED until this process exits (no-op if already held).

    Raises:
        LockBusy: A maintenance step (installer, uninstall, cache cleaning) is running.
    """
    path = lock_file(state_dir(app_root), MAINTENANCE)
    if str(path) in _PROCESS_HOLD or inherited_mode(path) is not None:
        return
    try:
        _PROCESS_HOLD[str(path)] = acquire(path, "shared", label)
    except LockBusy as error:
        raise LockBusy(f"Sniper is being installed, repaired, cleaned or removed by: {error}. "
                       "Try again when that has finished.") from None
    record = _records_dir(path) / f"{path.stem}.{os.getpid()}.json"
    atexit.register(record.unlink, missing_ok=True)


@contextmanager
def held(path: Path, mode: str, label: str, wait: float = 0.0) -> Iterator[None]:
    """Hold a lock for the duration of a ``with`` block (reentrant when inherited)."""
    if _covers(inherited_mode(path), mode):
        yield
        return
    fd = acquire(path, mode, label, wait)
    try:
        yield
    finally:
        (_records_dir(path) / f"{path.stem}.{os.getpid()}.json").unlink(missing_ok=True)
        os.close(fd)


def _exec_holding(args: argparse.Namespace) -> int:
    """Take the maintenance lock, then replace this process with the command, still holding it."""
    path = lock_file(Path(args.state_dir), MAINTENANCE)
    held_mode = inherited_mode(path)
    if held_mode is not None and not _covers(held_mode, args.mode):
        print(f"STOPPED: this runs inside a Sniper session that is using the install "
              f"({describe_holders(path)}). Close that session first, then run this again.",
              file=sys.stderr)
        return BUSY_EXIT
    if held_mode is None:
        try:
            fd = acquire(path, args.mode, args.label, args.wait)
        except LockBusy as error:
            print(f"STOPPED: {args.busy_message or 'Sniper is busy'}: in use by {error}.", file=sys.stderr)
            return BUSY_EXIT
        os.set_inheritable(fd, True)
        os.environ[ENV_FD], os.environ[ENV_MODE] = str(fd), args.mode
    os.execvp(args.command[0], args.command)
    return 127  # not reached


def _hold(args: argparse.Namespace) -> int:
    """Test utility: hold a lock, say so, sleep. Stands in for a render or an edit."""
    path = lock_file(Path(args.state_dir), args.name)
    try:
        fd = acquire(path, args.mode, args.label, args.wait)
    except LockBusy as error:
        print(f"busy: {error}", flush=True)
        return BUSY_EXIT
    print(f"held {args.name} {args.mode} pid {os.getpid()}", flush=True)
    time.sleep(args.seconds)
    os.close(fd)
    return 0


def _status(args: argparse.Namespace) -> int:
    """Exit 0 when nothing holds the maintenance lock, 1 (with holders) otherwise."""
    path = lock_file(Path(args.state_dir), MAINTENANCE)
    try:
        fd = acquire(path, "exclusive", "status probe")
    except LockBusy as error:
        print(f"held by {error}")
        return 1
    (_records_dir(path) / f"{path.stem}.{os.getpid()}.json").unlink(missing_ok=True)
    os.close(fd)
    print("free")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("exec", "hold", "status"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--state-dir", required=True)
        if name == "status":
            continue
        cmd.add_argument("--mode", choices=sorted(_MODES), required=True)
        cmd.add_argument("--label", required=True)
        cmd.add_argument("--wait", type=float, default=0.0)
    sub.choices["exec"].add_argument("--busy-message", default="")
    sub.choices["exec"].add_argument("command", nargs=argparse.REMAINDER)
    sub.choices["hold"].add_argument("--name", default=MAINTENANCE)
    sub.choices["hold"].add_argument("--seconds", type=float, default=3600.0)
    args = parser.parse_args(argv)
    if args.action == "exec":
        args.command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not args.command:
            parser.error("exec needs a command after --")
        return _exec_holding(args)
    return _hold(args) if args.action == "hold" else _status(args)


if __name__ == "__main__":
    raise SystemExit(main())
