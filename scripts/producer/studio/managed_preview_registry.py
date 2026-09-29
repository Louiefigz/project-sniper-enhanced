"""Bounded multi-project Studio registry storage: one private record per native project.

Each project owns its record, so opening project B never stops or switches project A, and a
crashed launch fences only its own project. Short registry transactions are serialized by a
private kernel lock that a caller waits for only until its own explicit monotonic deadline.
The legacy single-slot ``preview.json`` in the lease state root is read, never written: a live
view registered by earlier code is adopted here and keeps running. Ownership (launcher token,
hand-off holds, the user hold, refusals and the hold cap) is ``managed_preview_holds``;
``admit_open`` applies it to every open inside the registry transaction.
"""
from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Iterator

import native_work_lease
from headless.durable_files import (
    assert_private_lock_identity, bounded_directory_entries, open_private_dir, open_private_file,
    private_child_dir, read_private_file, write_pending_replace,
)
from studio.managed_preview_holds import (  # noqa: F401 (ownership names re-exported for registry callers)
    MAX_HOLDS, HoldsFull, ViewOwnedElsewhere, ViewOwner, owned_by, owner_tag, refuse_foreign, validate_ownership,
    view_owner, with_hold,
)
from studio.native_runtime import digest
from studio.studio_server import StudioServerError

REGISTRY_DIR = 'studio-previews'
LEGACY_RECORD = 'preview.json'
# Five batch clip reviewers plus one existing user-owned view. Each idle server and its
# descendants were measured at about 1.2 GiB in the C0679 audit, so this stays deliberately small.
MAX_MANAGED_PREVIEWS = 6
MAX_WAIT_SECONDS = 600.0
_LOCK = 'registry.lock'
_POLL_SECONDS = 0.1
_STATES = {'launching', 'running', 'stopped'}

@dataclasses.dataclass(frozen=True)
class Registry:
    """Descriptors held for one transaction: the registry directory and the lease state root."""

    directory: int
    root: int


def monotonic_until(wait_seconds: float) -> float:
    """Convert the caller's explicit allowance once; every wait below uses this deadline."""
    if type(wait_seconds) not in (int, float) or not 0 <= wait_seconds <= MAX_WAIT_SECONDS:
        raise ValueError(f'Studio registry wait must be between 0 and {MAX_WAIT_SECONDS:g} seconds')
    return time.monotonic() + wait_seconds


def record_name(project: str) -> str:
    """One record per canonical project path."""
    return hashlib.sha256(project.encode()).hexdigest()[:32] + '.json'


def record_path(project: str) -> Path:
    """Where an operator inspects one project's record."""
    return native_work_lease.state_root() / REGISTRY_DIR / record_name(project)


def _lock_until(lock: int, until: float) -> None:
    """Poll the kernel lock; a crashed holder's lock is released by the kernel."""
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= until:
                raise StudioServerError('Another Studio registry operation did not finish before this '
                                        'call deadline; nothing was changed, retry') from None
            time.sleep(min(_POLL_SECONDS, max(0.0, until - time.monotonic())))


@contextlib.contextmanager
def transaction(until: float) -> Iterator[Registry]:
    """Hold the registry lock for one bounded open/stop/status/adopt operation."""
    with contextlib.ExitStack() as stack:
        state = native_work_lease.state_root()
        state.mkdir(mode=0o700, exist_ok=True)
        root = open_private_dir(str(state))
        stack.callback(os.close, root)
        directory = private_child_dir(root, REGISTRY_DIR)
        stack.callback(os.close, directory)
        lock = open_private_file(directory, _LOCK, os.O_CREAT | os.O_RDWR)
        stack.callback(os.close, lock)
        _lock_until(lock, until)
        assert_private_lock_identity(directory, _LOCK, lock)
        yield Registry(directory, root)


def _validate(value: object, project: str | None = None) -> dict:
    """Records are closed-vocabulary dictionaries bound to one canonical project."""
    if not isinstance(value, dict) or value.get('schemaVersion') != 2 or value.get('state') not in _STATES:
        raise StudioServerError('Invalid managed Studio registry record')
    name = value.get('project')
    if not isinstance(name, str) or str(Path(name).resolve()) != name or (project and name != project):
        raise StudioServerError('Managed Studio record does not name its canonical project')
    validate_ownership(value)
    return value


def admit_open(registry: Registry, opened: tuple[str, object, dict | None], owner: ViewOwner | None,
               pending: dict | None = None) -> None:
    """Every open: an owned one never replaces a view held by others; a reuse records its hold.

    Nothing is written before the whole open is admitted: the proposed entry (a new MP4 binding or an
    adopted server) and this open's hold are validated together and published in one registry write,
    so a refusal leaves the prior record, and every other holder's binding, unchanged."""
    project, reused, stale = opened
    if stale is not None and owner is not None:
        refuse_foreign(project, stale, owner)
    if reused is not None:
        write_entry(registry, with_hold(pending or read_entry(registry, project), owner))
    elif pending is not None:
        write_entry(registry, pending)


def read_entry(registry: Registry, project: str) -> dict | None:
    """This project's record, or None when it has never been managed here."""
    name = record_name(project)
    try:
        os.stat(name, dir_fd=registry.directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return _validate(json.loads(read_private_file(registry.directory, name)), project)


def write_entry(registry: Registry, value: dict) -> None:
    """Durably replace exactly one project's record."""
    name = record_name(_validate(value)['project'])
    write_pending_replace(registry.directory, (name + '.pending', name),
                          (json.dumps(value, sort_keys=True) + '\n').encode())


def entries(registry: Registry) -> list[dict]:
    """Every managed project's record (bounded)."""
    names = [name for name in bounded_directory_entries(registry.directory, 4096) if name.endswith('.json')]
    return [_validate(json.loads(read_private_file(registry.directory, name))) for name in names]


def legacy_running(registry: Registry) -> dict | None:
    """The earlier single-slot registry's running view, read only (it may still own a server)."""
    try:
        os.stat(LEGACY_RECORD, dir_fd=registry.root, follow_symlinks=False)
    except FileNotFoundError:
        return None
    value = json.loads(read_private_file(registry.root, LEGACY_RECORD))
    if not isinstance(value, dict) or value.get('schemaVersion') != 1 or value.get('state') != 'running':
        return None
    return value


def media_binding(media: Path | None) -> dict | None:
    """Bind the review MP4 a view accompanies to its exact bytes."""
    if media is None:
        return None
    file = Path(media).resolve(strict=True)
    if not file.is_file():
        raise StudioServerError('Review media must be a regular file')
    return {'path': str(file), 'sha256': digest(file)}


def media_status(binding: dict | None) -> dict | None:
    """Report whether the bound review MP4 is still the exact bytes the view was opened with."""
    if not binding:
        return None
    file = Path(binding['path'])
    return {**binding, 'current': file.is_file() and digest(file) == binding['sha256']}
