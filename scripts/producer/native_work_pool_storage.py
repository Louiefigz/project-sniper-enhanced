"""Which shared space a directory's written bytes consume, or a refusal to charge it.

The pool charges disk to the space whose free bytes a directory consumes
(native_work_pool_disk.py). That is exact only for a local filesystem written straight to
a real disk, so accounting is refused (DiskUnaccountable), never guessed, for:
- a filesystem whose statfs f_flags lack MNT_LOCAL (smbfs, nfs, afpfs, webdav, autofs):
  its free bytes are a server's, shared with clients the pool cannot see;
- a filesystem type outside ACCOUNTED_TYPES, the f_fstypename strings macOS reports for
  APFS, HFS+, exFAT and FAT (confirmed on macOS 26 with attached images of each): devfs,
  nullfs/bindfs (stacked on another filesystem's bytes), tmpfs and other memory filesystems;
- a volume whose /dev/diskN node is not a real disk. The IOKit ancestry of the node (read
  in-process, no subprocess) must report Protocol Characteristics with a Physical
  Interconnect Location of Internal or External and a Physical Interconnect other than
  Virtual Interface. Disk images (UDIF, sparse image or bundle, RAM) report Virtual
  Interface; writing into one spends the free bytes of the filesystem holding its file, so
  charging it as its own space would admit the same bytes twice;
- an APFS volume whose container cannot be named from f_mntfromname.
Nothing is cached: a disk number reused after an eject is judged afresh on every call.
"""
from __future__ import annotations

import ctypes
import functools
import os
import platform
from types import SimpleNamespace

from native_work_lease import NativeWorkBusy

MNT_LOCAL = 0x00001000
ACCOUNTED_TYPES = ('apfs', 'hfs', 'exfat', 'msdos')
REAL_LOCATIONS = ('Internal', 'External')
VIRTUAL = 'Virtual Interface'
_UTF8 = 0x08000100  # kCFStringEncodingUTF8
_SEARCH_PARENTS = 3  # kIORegistryIterateRecursively | kIORegistryIterateParents
_PROTOCOL_KEYS = ('Physical Interconnect', 'Physical Interconnect Location')


class DiskUnaccountable(NativeWorkBusy):
    """Waiting cannot help: the directory's filesystem cannot be charged exactly."""


class Statfs(ctypes.Structure):
    """macOS struct statfs (64-bit inode layout, identical on arm64 and x86_64)."""

    _fields_ = [('f_bsize', ctypes.c_uint32), ('f_iosize', ctypes.c_int32), ('f_blocks', ctypes.c_uint64),
                ('f_bfree', ctypes.c_uint64), ('f_bavail', ctypes.c_uint64), ('f_files', ctypes.c_uint64),
                ('f_ffree', ctypes.c_uint64), ('f_fsid', ctypes.c_int32 * 2), ('f_owner', ctypes.c_uint32),
                ('f_type', ctypes.c_uint32), ('f_flags', ctypes.c_uint32), ('f_fssubtype', ctypes.c_uint32),
                ('f_fstypename', ctypes.c_char * 16), ('f_mntonname', ctypes.c_char * 1024),
                ('f_mntfromname', ctypes.c_char * 1024), ('f_flags_ext', ctypes.c_uint32),
                ('f_reserved', ctypes.c_uint32 * 7)]


@functools.cache
def _statfs_call() -> object:
    """libSystem statfs with the 64-bit inode layout (loaded once; results are never cached)."""
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    call = getattr(libc, 'statfs$INODE64' if platform.machine() == 'x86_64' else 'statfs')
    call.argtypes, call.restype = [ctypes.c_char_p, ctypes.POINTER(Statfs)], ctypes.c_int
    return call


def read_statfs(path: str) -> Statfs:
    """One statfs(2) call for a directory."""
    info = Statfs()
    if _statfs_call()(os.fsencode(path), ctypes.byref(info)) != 0:
        raise OSError(ctypes.get_errno(), 'statfs failed for disk accounting', path)
    return info


@functools.cache
def _frameworks() -> SimpleNamespace:
    """IOKit and CoreFoundation entry points with exact pointer-sized signatures."""
    io = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    pointer, port = ctypes.c_void_p, ctypes.c_uint32
    for function, restype, argtypes in (
            (io.IOBSDNameMatching, pointer, [port, port, ctypes.c_char_p]),
            (io.IOServiceGetMatchingService, port, [port, pointer]),
            (io.IORegistryEntrySearchCFProperty, pointer, [port, ctypes.c_char_p, pointer, pointer, port]),
            (io.IOObjectRelease, ctypes.c_int, [port]),
            (cf.CFStringCreateWithCString, pointer, [pointer, ctypes.c_char_p, port]),
            (cf.CFDictionaryGetValue, pointer, [pointer, pointer]),
            (cf.CFGetTypeID, ctypes.c_ulong, [pointer]), (cf.CFDictionaryGetTypeID, ctypes.c_ulong, []),
            (cf.CFStringGetTypeID, ctypes.c_ulong, []), (cf.CFRelease, None, [pointer]),
            (cf.CFStringGetCString, ctypes.c_bool, [pointer, ctypes.c_char_p, ctypes.c_long, port])):
        function.restype, function.argtypes = restype, argtypes
    return SimpleNamespace(io=io, cf=cf)


def _text(cf: object, dictionary: int, key: str) -> str | None:
    """One CFString value of a CFDictionary as text, else None."""
    name = cf.CFStringCreateWithCString(None, key.encode(), _UTF8)
    try:
        value = cf.CFDictionaryGetValue(dictionary, name)
    finally:
        cf.CFRelease(name)
    if not value or cf.CFGetTypeID(value) != cf.CFStringGetTypeID():
        return None
    buffer = ctypes.create_string_buffer(256)
    return buffer.value.decode() if cf.CFStringGetCString(value, buffer, 256, _UTF8) else None


def protocol(bsd_name: str) -> tuple[str | None, str | None]:
    """(Physical Interconnect, Location) nearest a BSD disk node in its IOService ancestry."""
    lib = _frameworks()
    service = lib.io.IOServiceGetMatchingService(0, lib.io.IOBSDNameMatching(0, 0, bsd_name.encode()))
    if not service:
        return None, None
    key = lib.cf.CFStringCreateWithCString(None, b'Protocol Characteristics', _UTF8)
    try:
        found = lib.io.IORegistryEntrySearchCFProperty(service, b'IOService', key, None, _SEARCH_PARENTS)
    finally:
        lib.cf.CFRelease(key)
        lib.io.IOObjectRelease(service)
    if not found:
        return None, None
    try:
        if lib.cf.CFGetTypeID(found) != lib.cf.CFDictionaryGetTypeID():
            return None, None
        interconnect, location = (_text(lib.cf, found, name) for name in _PROTOCOL_KEYS)
        return interconnect, location
    finally:
        lib.cf.CFRelease(found)


def _refuse(path: str, why: str) -> DiskUnaccountable:
    """The specific refusal, naming what would make the directory accountable."""
    return DiskUnaccountable(f'Disk accounting refused for {path}: {why}; the pool charges only local APFS, '
                             'HFS+, exFAT or FAT volumes on a real disk (not a disk image or network share)')


def _real_disk(path: str, source: str) -> str:
    """The BSD node of a local volume on a real disk; refuse images and anything unidentified."""
    node = source.removeprefix('/dev/')
    if not source.startswith('/dev/disk') or not node[4:5].isdigit():
        raise _refuse(path, f'its volume source {source!r} is not a disk node')
    interconnect, location = protocol(node)
    if location not in REAL_LOCATIONS or interconnect in (None, VIRTUAL):
        raise _refuse(path, f'{node} is not a real disk (IOKit protocol: {interconnect!r}, {location!r})')
    return node


def space(path: str, device: int) -> str:
    """Name the space whose free bytes this directory's filesystem reports, or refuse.

    Args:
        path: An existing directory.
        device: Its st_dev, which names a non-APFS space.

    Returns:
        'apfs-container:diskN' for an APFS volume (diskutil's APFSContainerReference) or
        'filesystem:<device>' for an HFS+, exFAT or FAT volume.

    Raises:
        DiskUnaccountable: A non-local, unsupported, image-backed or unidentified filesystem.
    """
    info = read_statfs(path)
    kind = info.f_fstypename.decode(errors='replace')
    if not info.f_flags & MNT_LOCAL:
        raise _refuse(path, f'{kind} is not a local filesystem')
    if kind not in ACCOUNTED_TYPES:
        raise _refuse(path, f'filesystem type {kind!r} is not accounted')
    node = _real_disk(path, info.f_mntfromname.decode(errors='replace'))
    if kind != 'apfs':
        return f'filesystem:{device}'
    whole = node.removeprefix('disk').split('s', 1)[0]
    if not whole.isdigit():
        raise _refuse(path, f'APFS volume {node!r} has no identifiable container')
    return f'apfs-container:disk{whole}'
