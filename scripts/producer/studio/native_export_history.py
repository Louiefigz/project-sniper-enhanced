"""Immutable attempt discovery pointers; all reuse still requires original stage proofs."""
from __future__ import annotations

import hashlib
import re
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


def history_rows(request: dict) -> list[dict]:
    """Read immutable registration pointers even after their media directories are removed."""
    directory = history_directory(request)
    if not directory.exists():
        return []
    real_directory(directory)
    files = [file for file in islice(directory.iterdir(), MAX_HISTORY + 2) if file.name != LOCK]
    require(len(files) <= MAX_HISTORY, 'Native project attempt history exceeds its 256-attempt bound')
    records = []
    for file in files:
        row = bound_json(file)
        require(row.get('schemaVersion') == 1 and row.get('project') == request['project'],
                'Native attempt history belongs to another project')
        require(Path(row['attempt']).is_absolute(), 'Native attempt history path is not absolute')
        validate_section_registration(row)
        records.append(row)
    return records


def validate_section_registration(row: dict) -> None:
    """Optional section metadata is closed and typed; ordinary historical pointers remain valid."""
    fields = {'sectionAttemptSequence', 'sectionPlanIdentity'}
    if not fields.intersection(row):
        return
    require(fields <= row.keys() and type(row['sectionAttemptSequence']) is int
            and row['sectionAttemptSequence'] > 0 and isinstance(row['sectionPlanIdentity'], str)
            and re.fullmatch('[0-9a-f]{64}', row['sectionPlanIdentity']) is not None,
            'invalid section attempt history')


def retained_request(row: dict) -> dict | None:
    """Revalidate retained bytes; absent media does not erase the immutable registration."""
    attempt = Path(row['attempt'])
    if not attempt.exists() and not attempt.is_symlink():
        return None
    real_directory(attempt)
    require(digest(attempt / 'export-request.json') == row['requestSha256'],
            'Native attempt history changed; preserve and reconcile the recorded attempt')
    original = bound_json(attempt / 'export-request.json')
    require(original.get('project') == row['project'] and original.get('output') == row['attempt'],
            'Native attempt registration differs from its request location')
    if 'sectionAttemptSequence' in row:
        require(original.get('sectionAttemptSequence') == row['sectionAttemptSequence']
                and original.get('revision', {}).get('identity') == row.get('sectionPlanIdentity')
                and original.get('revision', {}).get('mode') == 'initial-long',
                'section registration differs from its immutable request')
    return original


def known_attempts(request: dict) -> list[Path]:
    """Only retained exact attempts are media donors; registration alone grants no reuse."""
    return [Path(row['attempt']) for row in history_rows(request) if retained_request(row) is not None]


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
    if request.get('revision', {}).get('mode') == 'initial-long':
        row.update(sectionAttemptSequence=request.get('sectionAttemptSequence'),
                   sectionPlanIdentity=request['revision']['identity'])
    validate_section_registration(row)
    if file.exists():
        require(bound_json(file) == row, 'Native attempt history collision')
        return
    if request.get('revision', {}).get('mode') == 'initial-long':
        require(request.get('sectionAttemptSequence') == section_attempt_sequence(request),
                'section attempt generation is duplicate or rolled back')
    files = [entry for entry in islice(directory.iterdir(), MAX_HISTORY + 2) if entry.name != LOCK]
    require(len(files) < MAX_HISTORY,
            'Native project attempt history is full; preserve and reconcile earlier attempts')
    write_new(file, row)


def section_attempt_sequence(request: dict) -> int:
    """Next section launch generation, assigned while holding the existing attempt reservation."""
    return max((row['sequence'] for row in section_registrations(request)), default=0) + 1


def section_registrations(request: dict) -> list[dict]:
    """Keep the section high-water mark durable independently of reusable artifact retention."""
    sections = []
    for row in history_rows(request):
        original = retained_request(row)
        sequence = row.get('sectionAttemptSequence')
        identity = row.get('sectionPlanIdentity')
        if sequence is None and original is not None and original.get('revision', {}).get('mode') == 'initial-long':
            sequence = original.get('sectionAttemptSequence')
            identity = original.get('revision', {}).get('identity')
        if sequence is None and identity is None:
            continue
        require(type(sequence) is int and sequence > 0 and isinstance(identity, str)
                and re.fullmatch('[0-9a-f]{64}', identity) is not None, 'invalid section attempt history')
        sections.append({'sequence': sequence, 'planIdentity': identity, 'attempt': row['attempt']})
    return sections


def require_current_section_attempt(request: dict) -> None:
    """A later admitted attempt supersedes old section assembly and delivery, even with identical inputs."""
    sequence = request.get('sectionAttemptSequence')
    require(type(sequence) is int and sequence > 0, 'section attempt lacks current launch generation')
    records = section_registrations(request)
    owners = [row['attempt'] for row in records if row['sequence'] == sequence]
    require(owners == [request['output']], 'section attempt generation is missing or ambiguous')
    require(all(row['planIdentity'] == request['revision']['identity'] for row in records
                if row['sequence'] == sequence), 'section attempt manifest differs from its registration')
    require(max(row['sequence'] for row in records) == sequence,
            'section attempt was superseded; preserve its seals but do not publish its result')


def lineage_attempts(request: dict) -> list[Path]:
    """Recorded attempts of verified ancestor projects; callers still check clip and content."""
    from studio.native_clip_lineage import verified_ancestors
    attempts: list[Path] = []
    for ancestor in verified_ancestors(Path(request['project'])):
        attempts += known_attempts({**request, 'project': str(ancestor)})
    return attempts
