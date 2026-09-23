"""Immutable attempt discovery pointers; all reuse still requires original stage proofs."""
from __future__ import annotations

import hashlib
from itertools import islice
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator

from cut_preview_io import bound_json, real_directory, write_new
from studio.native_runtime import digest
from studio.native_stage_evidence import require
from headless.durable_files import locked_private_dir

MAX_HISTORY = 256
LOCK = '.attempts.lock'


def candidate_attempts(request: dict) -> list[Path]:
    """Bound sibling discovery and merge immutable cross-parent history pointers."""
    parent = Path(request['output']).parent
    real_directory(parent)
    entries = list(islice(parent.iterdir(), MAX_HISTORY + 1))
    require(len(entries) <= MAX_HISTORY,
            'Recovery search exceeds 256 entries; use a dedicated attempt directory')
    return sorted(attempt for attempt in set(entries + known_attempts(request))
                  if not attempt.is_symlink() and attempt.is_dir())


@contextmanager
def attempt_reservation(request: dict) -> Iterator[None]:
    """Serialize discovery/publication so simultaneous retries cannot both start fresh."""
    directory = history_directory(request)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked_private_dir(str(directory), LOCK):
        yield


def history_directory(request: dict) -> Path:
    """Keep discovery outside authored inputs and stable across runtime installations."""
    project_key = hashlib.sha256(request['project'].encode()).hexdigest()
    return Path(request['runtime']).parent.parent / 'native-export-history' / project_key


def known_attempts(request: dict) -> list[Path]:
    """Read bounded exact pointers without treating their existence as render approval."""
    directory = history_directory(request)
    if not directory.exists():
        return []
    real_directory(directory)
    files = [file for file in islice(directory.iterdir(), MAX_HISTORY + 2) if file.name != LOCK]
    require(len(files) <= MAX_HISTORY, 'Native project attempt history exceeds its 256-attempt bound')
    attempts = []
    for file in files:
        row = bound_json(file)
        require(row.get('schemaVersion') == 1 and row.get('project') == request['project'],
                'Native attempt history belongs to another project')
        attempt = Path(row['attempt'])
        if not attempt.exists() and not attempt.is_symlink():
            continue  # Removed artifacts provide no reusable authority.
        real_directory(attempt)
        require(attempt.is_absolute() and digest(attempt / 'export-request.json') == row['requestSha256'],
                'Native attempt history changed; preserve and reconcile the recorded attempt')
        attempts.append(attempt)
    return attempts


def register_attempt(request: dict) -> None:
    """Publish one immutable discovery reference only after the immutable request exists."""
    directory = history_directory(request)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    real_directory(directory)
    attempt = Path(request['output'])
    key = hashlib.sha256(str(attempt).encode()).hexdigest()
    file = directory / f'{key}.json'
    row = {'schemaVersion': 1, 'project': request['project'], 'attempt': str(attempt),
           'requestSha256': digest(attempt / 'export-request.json')}
    if file.exists():
        require(bound_json(file) == row, 'Native attempt history collision')
        return
    files = [entry for entry in islice(directory.iterdir(), MAX_HISTORY + 2) if entry.name != LOCK]
    require(len(files) < MAX_HISTORY,
            'Native project attempt history is full; preserve and reconcile earlier attempts')
    write_new(file, row)
