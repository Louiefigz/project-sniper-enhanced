"""Low-level durable storage helpers for the Palmier sync lock."""
from __future__ import annotations

import fcntl
import json
import os
import secrets
from typing import Any


def open_lock(path: str) -> int:
    """Open a private lock inode without inheriting it into child processes."""
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, 0o600)


def mutex(path: str) -> int:
    """Acquire and return a blocking exclusive mutex descriptor."""
    fd = open_lock(path)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def unlock_close(fd: int | None) -> None:
    """Release and close a descriptor when it exists."""
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def read_fd(fd: int) -> dict[str, Any]:
    """Read a bounded JSON object from a lock descriptor."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        value = json.loads(os.read(fd, 16_384).decode())
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def write_fd(fd: int, value: dict[str, Any]) -> None:
    """Durably replace the JSON object stored in a lock descriptor."""
    data = json.dumps(value, sort_keys=True).encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, data)
    os.fsync(fd)


def try_lock(path: str) -> tuple[int | None, dict[str, Any]]:
    """Try an exclusive lock and return either its descriptor or its owner."""
    fd = open_lock(path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        owner = read_fd(fd)
        os.close(fd)
        return None, owner
    except BaseException:
        os.close(fd)
        raise
    return fd, {}


def read_json(path: str) -> dict[str, Any]:
    """Read a JSON object, treating missing or malformed state as empty."""
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def atomic_json(path: str, value: dict[str, Any]) -> None:
    """Atomically and durably replace a JSON file."""
    temp = f"{path}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    try:
        with open(temp, "x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def remove(path: str) -> None:
    """Remove optional lock state."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
