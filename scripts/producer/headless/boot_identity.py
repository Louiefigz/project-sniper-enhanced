"""Derive a stable, non-secret identity for the current operating-system boot."""
from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess

_LINUX_BOOT_PATH = "/proc/sys/kernel/random/boot_id"
_LINUX_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DARWIN_BOOT = re.compile(
    r"\{\s*sec\s*=\s*(\d+),\s*usec\s*=\s*(\d+)\s*\}(?:\s+.*)?")


class BootIdentityError(RuntimeError):
    """The current OS boot cannot be identified safely."""


def _digest(system: str, token: str) -> str:
    payload = f"sniper-boot-id-v1\0{system}\0{token}".encode("ascii")
    return f"boot-v1-{hashlib.sha256(payload).hexdigest()}"


def _linux_token() -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        fd = os.open(_LINUX_BOOT_PATH, flags)
        try:
            value = os.read(fd, 128).decode("ascii").strip().lower()
        finally:
            os.close(fd)
    except (OSError, UnicodeError) as exc:
        raise BootIdentityError("cannot read the Linux kernel boot ID") from exc
    if not _LINUX_UUID.fullmatch(value):
        raise BootIdentityError("Linux kernel returned an invalid boot ID")
    return value


def _darwin_token() -> str:
    command = ["/usr/sbin/sysctl", "-n", "kern.boottime"]
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
    try:
        result = subprocess.run(
            command, capture_output=True, check=False, close_fds=True,
            env=environment, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BootIdentityError("cannot query the Darwin kernel boot time") from exc
    match = _DARWIN_BOOT.fullmatch(result.stdout.strip())
    if result.returncode or match is None:
        raise BootIdentityError("Darwin kernel returned an invalid boot time")
    seconds, microseconds = match.groups()
    if int(microseconds) >= 1_000_000:
        raise BootIdentityError("Darwin kernel returned invalid microseconds")
    return f"{int(seconds)}.{int(microseconds):06d}"


def read_boot_id() -> str:
    """Return one domain-separated identity that changes only after reboot."""
    system = platform.system()
    if system == "Linux":
        return _digest("linux", _linux_token())
    if system == "Darwin":
        return _digest("darwin", _darwin_token())
    raise BootIdentityError(f"unsupported operating system: {system or 'unknown'}")
