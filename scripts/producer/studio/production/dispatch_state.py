"""The media dispatcher's own records and readings: identity (readiness and exit), liveness, log, slots, engine.

The identity record (``dispatcher.json``) is written privately when the dispatcher holds its
single-instance lock and again when it exits. ``status`` reports a dispatcher as running only while
that exact identity (pid, process group and start time) is alive and has not recorded its exit, so a
reused PID never counts. The log is bounded (``LOG_LIMIT_BYTES``); past it, one marker is written.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from headless.durable_files import DurableFileError, open_private_dir, read_private_file, write_pending_replace
from studio.production import media, process
from studio.production.task_schema import holds_slot

IDENTITY, LOCK, LOG = 'dispatcher.json', 'dispatcher.lock', 'dispatcher.log'
LOG_LIMIT_BYTES = 1024 ** 2


def utc() -> str:
    """Wall-clock evidence for records and logs."""
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class BoundedLog:
    """Append JSON lines until the log reaches its bound; then one marker and nothing more."""

    def __init__(self, path: Path) -> None:
        """Log to ``path`` (the dispatcher's own output file)."""
        self.path, self.full = path, False

    def write(self, event: str, **fields: object) -> None:
        """One bounded line."""
        line = json.dumps({'at': utc(), 'event': event, **fields}, default=str) + '\n'
        size = self.path.stat().st_size if self.path.exists() else 0
        if self.full or size + len(line) > LOG_LIMIT_BYTES:
            line = '' if self.full else json.dumps({'at': utc(), 'event': 'log-bound-reached'}) + '\n'
            self.full = True
        with self.path.open('a') as handle:
            handle.write(line)


def write_identity(directory: Path, value: dict) -> None:
    """Replace the dispatcher's identity record (private, durable)."""
    fd = open_private_dir(str(directory))
    try:
        write_pending_replace(fd, (f'.{IDENTITY}.pending', IDENTITY), (json.dumps(value) + '\n').encode())
    finally:
        os.close(fd)


def read_identity(root: Path, batch_id: str) -> dict | None:
    """The last dispatcher identity record of this batch, or None."""
    directory = root / media.STATE / batch_id
    if not (directory / IDENTITY).is_file():
        return None
    fd = open_private_dir(str(directory))
    try:
        return json.loads(read_private_file(fd, IDENTITY, 64 * 1024).decode('utf-8'))
    finally:
        os.close(fd)


def status(root: Path, batch_id: str) -> dict:
    """Whether this batch's dispatcher runs now: its recorded exact identity is alive and has not exited."""
    try:
        record = read_identity(root, batch_id)
    except (DurableFileError, OSError, ValueError) as error:
        return {'running': False, 'identity': None, 'problem': f'{type(error).__name__}: {error}'}
    if record is None:
        return {'running': False, 'identity': None}
    running = record.get('exit') is None and process.alive(record['identity']) is True
    return {'running': running, 'identity': record['identity'], 'startedAt': record.get('startedAt'),
            'exit': record.get('exit')}


def engine_refusal(record: dict, engine: dict) -> str | None:
    """Why this checkout's engine may not dispatch the batch's media, or None (it is the frozen engine)."""
    frozen = record['engine']
    if frozen is None or frozen['identity'] == engine['identity']:
        return None
    return (f'this checkout\'s engine {engine["identity"][:12]}… is not the engine batch {record["batchId"]} froze '
            f'({frozen["identity"][:12]}…); run native_batch.py dispatch from that engine')


def busy_slots(record: dict) -> int:
    """Pool slots held now: media tasks holding theirs, and running launches no such task owns."""
    held = [task for task in record['production']['tasks'].values() if task['kind'] == 'media' and holds_slot(task)]
    owned = {(task['clipId'], task['attempt']) for task in held if task['attempt']}
    loose = sum(1 for clip_id, clip in record['clips'].items() for row in clip['attempts']
                if row['status'] == 'running' and (clip_id, row['id']) not in owned)
    return len(held) + loose
