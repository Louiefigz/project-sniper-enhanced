#!/usr/bin/env python3
"""Kernel locks that keep Sniper maintenance and active work apart.

POSIX uses inherited flock descriptors. Windows serializes both modes through a
byte-range lock and keeps a parent process alive while its command runs. Holder
records improve messages but never replace the kernel lock as authority.
"""
from __future__ import annotations

import argparse
import atexit
import errno
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import sniper_file_lock
MAINTENANCE = "maintenance"
RUNTIME_BUILD = "runtime-build"
ENV_FD = "SNIPER_LOCK_FD"
ENV_MODE = "SNIPER_LOCK_MODE"
BUSY_EXIT = 75  # EX_TEMPFAIL: try again later
_MODES = {"exclusive", "shared"}
_PROCESS_HOLD: dict[str, int] = {}
class LockBusy(RuntimeError):
    """The lock is held by another process in a conflicting mode."""


def state_dir(app_root: Path) -> Path:
    """Use package state when an installer is present, otherwise the developer cache."""
    if (app_root / "install/lib/common.sh").is_file():
        return app_root / "runtime" / "state"
    return app_root / "templates/motion/.sniper-native-runtime/.locks"


def lock_file(directory: Path, name: str) -> Path:
    """Path of one named lock file inside a state directory."""
    return directory / f"{name}.lock"


def _open(path: Path) -> int:
    """Open (creating if needed) a lock file; never truncates, never deletes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    sniper_file_lock.prepare(fd)
    return fd


def inherited_mode(path: Path) -> str | None:
    """The mode this process already holds ``path`` in through an inherited descriptor."""
    raw, mode = os.environ.get(ENV_FD, ""), os.environ.get(ENV_MODE, "")
    if not raw.isdigit() or mode not in _MODES:
        return None
    if sniper_file_lock.WINDOWS:
        record = _records_dir(path) / f"{path.stem}.{raw}.json"
        try:
            row = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        same = row.get("pid") == int(raw) and row.get("path") == str(path.resolve())
        return mode if same and _pid_alive(int(raw)) and row.get("mode") == mode else None
    try:
        held, wanted = os.fstat(int(raw)), os.stat(path)
    except OSError:
        return None
    same = (held.st_dev, held.st_ino) == (wanted.st_dev, wanted.st_ino)
    return mode if same else None


def _pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists."""
    if sniper_file_lock.WINDOWS:
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_pid_alive(pid: int) -> bool:
    """Probe a Windows process without sending it a terminating signal."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _records_dir(path: Path) -> Path:
    return path.parent / "lock-holders"


def _write_record(path: Path, mode: str, label: str) -> Path:
    """Note who holds the lock, for messages only; the flock is the authority.

    Records of processes that have exited are pruned here, so they never pile up.
    """
    directory = _records_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.json"):
        pid = old.stem.rsplit(".", 1)[-1]
        if pid.isdigit() and not _pid_alive(int(pid)):
            old.unlink(missing_ok=True)
    record = directory / f"{path.stem}.{os.getpid()}.json"
    record.write_text(json.dumps({"pid": os.getpid(), "mode": mode, "label": label,
                                  "path": str(path.resolve()),
                                  "since": time.strftime("%H:%M:%S")}), encoding="utf-8")
    return record


def _pids_with_file_open(path: Path) -> list[int]:
    """Every process with the lock file open, whether or not it wrote a record."""
    if sniper_file_lock.WINDOWS:
        return []
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
            sniper_file_lock.try_lock(fd, mode)
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
        sniper_file_lock.unlock(fd)
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
    acquired = held_mode is None
    if acquired:
        try:
            fd = acquire(path, args.mode, args.label, args.wait)
        except LockBusy as error:
            print(f"STOPPED: {args.busy_message or 'Sniper is busy.'}\n  In use by: {error}.", file=sys.stderr)
            return BUSY_EXIT
        if sniper_file_lock.WINDOWS:
            os.environ[ENV_FD] = str(os.getpid())
        else:
            os.set_inheritable(fd, True)
            os.environ[ENV_FD] = str(fd)
        os.environ[ENV_MODE] = args.mode
    if sniper_file_lock.WINDOWS:
        if not acquired:
            return subprocess.run(args.command, check=False).returncode
        try:
            return subprocess.run(args.command, check=False).returncode
        finally:
            (_records_dir(path) / f"{path.stem}.{os.getpid()}.json").unlink(missing_ok=True)
            sniper_file_lock.unlock(fd)
            os.close(fd)
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
    sniper_file_lock.unlock(fd)
    os.close(fd)
    return 0


def _status(args: argparse.Namespace) -> int:
    """Exit 0 when the maintenance lock could be taken in ``--mode`` now, 1 (naming holders) if not.

    A momentary answer for messages only; work that must stay exclusive holds the
    lock itself (``exec``) instead of relying on this.
    """
    path = lock_file(Path(args.state_dir), MAINTENANCE)
    try:
        fd = acquire(path, args.mode, "status probe")
    except LockBusy as error:
        print(f"held by {error}")
        return 1
    (_records_dir(path) / f"{path.stem}.{os.getpid()}.json").unlink(missing_ok=True)
    sniper_file_lock.unlock(fd)
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
            cmd.add_argument("--mode", choices=sorted(_MODES), default="exclusive")
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
