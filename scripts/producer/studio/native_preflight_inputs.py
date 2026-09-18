"""Bounded read-only source snapshots for native-project static preflight.

Media is identified by filesystem metadata, not decoded or content-qualified.
This snapshot is never render admission, a cache proof, or delivery approval.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from cut_preview_io import digest, file_hash, real_directory

MAX_FILES = 512
MAX_DIRECTORIES = 128
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MEDIA_SUFFIXES = frozenset({'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi',
                            '.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus'})
EXCLUDED_DIRECTORIES = frozenset({'.git', '.hyperframes', 'node_modules'})


def identity(path: Path) -> dict:
    """Require a canonical regular file; keep exact, non-rounded stat fields."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.resolve() != path:
        raise RuntimeError(f'Native preflight requires a regular unlinked source: {path}')
    return {key: str(getattr(info, key)) for key in
            ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_size',
             'st_mtime_ns', 'st_ctime_ns', 'st_nlink')}


def inventory(project: Path) -> tuple[list[Path], dict]:
    """Bound directory traversal and reject symlinks before invoking the SDK."""
    real_directory(project)
    pending, files, directories = [project], [], {}
    while pending:
        current = pending.pop()
        if len(directories) >= MAX_DIRECTORIES or len(current.relative_to(project).parts) > 16:
            raise RuntimeError('Native preflight directory inventory exceeds its bound')
        real_directory(current)
        info = current.stat()
        directories[str(current)] = [str(info.st_dev), str(info.st_ino)]
        _children(current, pending, files)
    return sorted(files), directories


def _children(current: Path, pending: list[Path], files: list[Path]) -> None:
    """Admit only real project files, excluding named SDK/cache directories."""
    with os.scandir(current) as entries:
        for entry in entries:
            _admit_entry(entry, pending, files)


def _admit_entry(entry: os.DirEntry, pending: list[Path], files: list[Path]) -> None:
    """Keep the bounded inventory's individual admission decisions shallow."""
    if len(files) + len(pending) > MAX_FILES + MAX_DIRECTORIES:
        raise RuntimeError('Native preflight file inventory exceeds its bound')
    if entry.is_symlink():
        raise RuntimeError(f'Native preflight refuses a linked input: {entry.path}')
    target = Path(entry.path)
    if entry.is_dir(follow_symlinks=False):
        if entry.name not in EXCLUDED_DIRECTORIES:
            pending.append(target)
        return
    if not entry.is_file(follow_symlinks=False):
        raise RuntimeError(f'Native preflight refuses a special input: {entry.path}')
    files.append(target)
    if len(files) > MAX_FILES:
        raise RuntimeError('Native preflight file inventory exceeds its bound')


def source_state(project: Path) -> dict:
    """Hash small source/dependency files once, retaining media stat identities."""
    paths, directories = inventory(project)
    if project / 'index.html' not in paths:
        raise RuntimeError('Native preflight requires an existing index.html')
    files, remaining = {}, MAX_SOURCE_BYTES
    for path in paths:
        before = identity(path)
        media = path.suffix.lower() in MEDIA_SUFFIXES
        size = int(before['st_size'])
        if size <= 0 or (not media and size > min(MAX_FILE_BYTES, remaining)):
            raise RuntimeError(f'Native preflight source is empty or exceeds its bound: {path}')
        hashed = None if media else file_hash(path, min(MAX_FILE_BYTES, remaining))
        if identity(path) != before:
            raise RuntimeError('Native preflight source changed while reading')
        remaining -= 0 if media else size
        files[path.relative_to(project).as_posix()] = {
            'identity': before, 'sha256': hashed, 'mediaMetadataOnly': media}
    if inventory(project) != (paths, directories):
        raise RuntimeError('Native preflight inventory changed while reading')
    return {'project': str(project), 'files': files, 'directories': directories,
            'excludedDirectories': sorted(EXCLUDED_DIRECTORIES),
            'sourceStateSha256': digest(files), 'mediaContentQualified': False}


def require_unchanged(project: Path, original: dict) -> None:
    """Refuse source, asset identity or inventory drift; never reuse stale lint."""
    if source_state(project) != original:
        raise RuntimeError('Native preflight project changed during the check')
