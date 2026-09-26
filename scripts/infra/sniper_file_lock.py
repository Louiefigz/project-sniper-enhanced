"""Small cross-platform kernel file-lock adapter for sniper_lock."""
from __future__ import annotations

import errno
import os

WINDOWS = os.name == "nt"

if WINDOWS:
    import msvcrt
else:
    import fcntl


def prepare(fd: int) -> None:
    """Ensure Windows has the byte range that msvcrt locks."""
    if WINDOWS and os.fstat(fd).st_size == 0:
        os.write(fd, b"0")
        os.lseek(fd, 0, os.SEEK_SET)


def try_lock(fd: int, mode: str) -> None:
    """Take a nonblocking kernel lock or raise EACCES/EAGAIN."""
    if WINDOWS:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EDEADLK):
                raise OSError(errno.EAGAIN, "lock busy") from error
            raise
        return
    operation = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
    fcntl.flock(fd, operation | fcntl.LOCK_NB)


def unlock(fd: int) -> None:
    """Release a held lock before closing its descriptor."""
    if WINDOWS:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
