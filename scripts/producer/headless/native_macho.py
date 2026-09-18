"""Minimal Mach-O load-command reader for the native media decoder closure.

Reads only what the native admission runtime needs to name and hash a decoder's
dynamic-library closure: `LC_LOAD_DYLIB`, `LC_LOAD_WEAK_DYLIB`,
`LC_REEXPORT_DYLIB`, `LC_LAZY_LOAD_DYLIB`, `LC_LOAD_UPWARD_DYLIB` and
`LC_RPATH`. It needs no Xcode tools (`otool` is a stub on a Mac without the
command-line tools) and never executes the binary it reads.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass

_MH_MAGIC_64 = 0xFEEDFACF
_FAT_MAGIC = 0xCAFEBABE
_FAT_MAGIC_64 = 0xCAFEBABF
_CPU_ARM64 = 0x0100000C
_CPU_X86_64 = 0x01000007
_LC_REQ_DYLD = 0x80000000
_DYLIB_COMMANDS = {0xC, 0x18 | _LC_REQ_DYLD, 0x1F | _LC_REQ_DYLD, 0x20, 0x23 | _LC_REQ_DYLD}
_LC_RPATH = 0x1C | _LC_REQ_DYLD
_MAX_HEADER_BYTES = 4 * 1024 * 1024
_SYSTEM_PREFIXES = ("/usr/lib/", "/System/")


class MachOError(RuntimeError):
    """The file is not a Mach-O image this reader accepts."""


@dataclass(frozen=True)
class MachODependencies:
    """Install names and run paths declared by one Mach-O image."""

    dylibs: tuple[str, ...]
    rpaths: tuple[str, ...]


def _slice_offset(data: bytes, cpu: int) -> int:
    """Return the file offset of the thin image for ``cpu`` inside a fat file."""
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic not in (_FAT_MAGIC, _FAT_MAGIC_64):
        return 0
    count = struct.unpack_from(">I", data, 4)[0]
    wide = magic == _FAT_MAGIC_64
    stride, fmt = (32, ">iiQQI") if wide else (20, ">iiIII")
    if not 0 < count <= 16:
        raise MachOError("fat header architecture count is out of range")
    for index in range(count):
        arch_cpu, _sub, offset, _size, _align = struct.unpack_from(fmt, data, 8 + index * stride)
        if arch_cpu == cpu:
            return offset
    raise MachOError("no slice for this Mac's architecture")


def _commands(image: bytes) -> list[tuple[int, bytes]]:
    """Split the load-command region of one thin 64-bit image."""
    if len(image) < 32 or struct.unpack_from("<I", image, 0)[0] != _MH_MAGIC_64:
        raise MachOError("not a 64-bit Mach-O image")
    ncmds, sizeofcmds = struct.unpack_from("<II", image, 16)
    if ncmds > 4096 or 32 + sizeofcmds > len(image):
        raise MachOError("load-command region is out of range")
    rows, offset = [], 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", image, offset)
        if size < 8 or offset + size > 32 + sizeofcmds:
            raise MachOError("load command size is out of range")
        rows.append((cmd, image[offset:offset + size]))
        offset += size
    return rows


def _string_at(command: bytes, field_offset: int) -> str:
    """Decode the NUL-terminated string a load command points at."""
    start = struct.unpack_from("<I", command, field_offset)[0]
    if not 8 <= start < len(command):
        raise MachOError("load command string offset is out of range")
    raw = command[start:].split(b"\0", 1)[0]
    return raw.decode("utf-8")


def read_dependencies(path: str, cpu: int | None = None) -> MachODependencies:
    """Read declared dylib install names and run paths without executing ``path``.

    Args:
        path: Absolute path of a Mach-O executable or dylib.
        cpu: Mach-O CPU type to select from a fat file; defaults to this Mac's.

    Returns:
        The declared dependencies in load-command order.
    """
    target = cpu if cpu is not None else (_CPU_ARM64 if os.uname().machine == "arm64" else _CPU_X86_64)
    with open(path, "rb") as handle:
        head = handle.read(_MAX_HEADER_BYTES)
        offset = _slice_offset(head, target)
        handle.seek(offset)
        image = handle.read(_MAX_HEADER_BYTES)
    dylibs, rpaths = [], []
    for cmd, body in _commands(image):
        if cmd in _DYLIB_COMMANDS:
            dylibs.append(_string_at(body, 8))
        elif cmd == _LC_RPATH:
            rpaths.append(_string_at(body, 8))
    return MachODependencies(tuple(dylibs), tuple(rpaths))


def _expand(template: str, loader: str, executable: str) -> str:
    """Expand @loader_path/@executable_path in an install name or run path."""
    if template.startswith("@loader_path"):
        return os.path.dirname(loader) + template[len("@loader_path"):]
    if template.startswith("@executable_path"):
        return os.path.dirname(executable) + template[len("@executable_path"):]
    return template


def _candidate(name: str, loader: str, executable: str, rpaths: list[str]) -> str | None:
    """The path dyld opens for one install name (before symlinks), or None for OS images."""
    if name.startswith(_SYSTEM_PREFIXES):
        return None
    if name.startswith("@rpath/"):
        for rpath in rpaths:
            candidate = os.path.normpath(os.path.join(_expand(rpath, loader, executable), name[len("@rpath/"):]))
            if os.path.isfile(candidate):
                return candidate
        raise MachOError(f"unresolved run-path dependency {name} of {loader}")
    candidate = os.path.normpath(_expand(name, loader, executable))
    if not os.path.isabs(candidate) or not os.path.isfile(candidate):
        raise MachOError(f"missing dependency {name} of {loader}")
    return candidate


def link_chain(path: str) -> set[str]:
    """Every path a lookup of ``path`` passes through: as named, with its directory
    resolved, and each hop of a final-component symlink chain (bounded)."""
    seen = {os.path.normpath(path)}
    current = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    for _ in range(32):
        seen.add(current)
        if not os.path.islink(current):
            break
        target = os.readlink(current)
        joined = target if os.path.isabs(target) else os.path.join(os.path.dirname(current), target)
        current = os.path.join(os.path.realpath(os.path.dirname(joined)), os.path.basename(joined))
    seen.add(os.path.realpath(path))
    return seen


@dataclass(frozen=True)
class DependencyClosure:
    """Every non-OS image a set of executables loads."""

    images: dict[str, str]
    """``{real_path: declared_name}`` for each executable and dylib."""
    opened: frozenset[str]
    """Every path dyld opens on the way (install-name and run-path expansions,
    executable paths as given) plus every real path; a sandbox checks these."""


def dependency_paths(executables: tuple[str, ...]) -> DependencyClosure:
    """Images and opened paths for ``executables`` (OS images under /usr/lib and /System excluded)."""
    images: dict[str, str] = {}
    opened: set[str] = set()
    for executable in executables:
        real = os.path.realpath(executable)
        opened.update(link_chain(executable))
        pending = [(real, executable, [])]
        while pending:
            image, declared, inherited = pending.pop()
            if image in images:
                continue
            images[image] = declared
            deps = read_dependencies(image)
            rpaths = [_expand(item, image, real) for item in deps.rpaths] + inherited
            for name in deps.dylibs:
                candidate = _candidate(name, image, real, rpaths)
                if candidate is not None:
                    resolved = os.path.realpath(candidate)
                    opened.update(link_chain(candidate))
                    pending.append((resolved, name, rpaths))
    return DependencyClosure(images, frozenset(opened))


def dependency_closure(executables: tuple[str, ...]) -> dict[str, str]:
    """Map every non-OS image loaded by ``executables`` to the path that names it."""
    return dependency_paths(executables).images
