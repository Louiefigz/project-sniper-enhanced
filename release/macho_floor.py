"""The oldest macOS a folder of Apple-silicon binaries runs on, read from the files themselves.

Every Mach-O file names the minimum macOS it was built for (``LC_BUILD_VERSION`` minos, or the
older ``LC_VERSION_MIN_MACOSX``). Package metadata can understate it, so the release measures it.
Pure Python: ``otool`` is not on a Mac without the developer tools.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

_THIN_64 = b"\xcf\xfa\xed\xfe"          # MH_MAGIC_64, little endian
_FAT = (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")   # FAT_MAGIC / FAT_MAGIC_64, big endian
_ARM64 = 0x0100000C
_LC_BUILD_VERSION = 0x32
_LC_VERSION_MIN_MACOSX = 0x24
_PLATFORM_MACOS = 1


def _version(encoded: int) -> str:
    return f"{encoded >> 16}.{(encoded >> 8) & 0xFF}"


def version_key(version: str) -> tuple[int, ...]:
    """``"13.5"`` -> ``(13, 5)``, for comparing versions."""
    return tuple(int(part) for part in version.split("."))


def _slice_floor(data: bytes, offset: int) -> str | None:
    """The macOS floor of the arm64 thin Mach-O at ``offset``, or None (another CPU, or none named)."""
    if data[offset:offset + 4] != _THIN_64:
        return None
    cputype, _, _, ncmds = struct.unpack_from("<iiII", data, offset + 4)
    if cputype != _ARM64:
        return None
    at = offset + 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, at)
        if cmd == _LC_BUILD_VERSION and struct.unpack_from("<I", data, at + 8)[0] == _PLATFORM_MACOS:
            return _version(struct.unpack_from("<I", data, at + 12)[0])
        if cmd == _LC_VERSION_MIN_MACOSX:
            return _version(struct.unpack_from("<I", data, at + 8)[0])
        at += size
    return None


def file_floor(path: Path) -> str | None:
    """The macOS floor of one file's arm64 code, or None when it is not an arm64 Mach-O file."""
    with path.open("rb") as handle:
        magic = handle.read(4)
        if magic != _THIN_64 and magic not in _FAT:
            return None
        data = magic + handle.read()
    try:
        if magic == _THIN_64:
            return _slice_floor(data, 0)
        count = struct.unpack_from(">I", data, 4)[0]
        if count > 30:          # a Java class file shares the fat magic; its "count" is a version
            return None
        wide = magic == _FAT[1]
        for index in range(count):
            if wide:
                cputype, _, offset = struct.unpack_from(">iiQ", data, 8 + index * 32)
            else:
                cputype, _, offset = struct.unpack_from(">iiI", data, 8 + index * 20)
            if cputype == _ARM64:
                return _slice_floor(data, offset)
    except struct.error:        # truncated: not a usable Mach-O file
        return None
    return None


def folder_floor(root: Path) -> tuple[str, list[str], int]:
    """(highest floor, files that set it relative to ``root``, Mach-O files read) for a folder."""
    highest, setters, count = "0.0", [], 0
    for folder, _, names in os.walk(root):
        for name in names:
            path = Path(folder) / name
            if path.is_symlink() or not path.is_file():
                continue
            floor = file_floor(path)
            if floor is None:
                continue
            count += 1
            if version_key(floor) > version_key(highest):
                highest, setters = floor, []
            if floor == highest:
                setters.append(str(path.relative_to(root)))
    return highest, sorted(setters), count
