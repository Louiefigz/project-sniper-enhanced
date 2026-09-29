"""Typed operator inputs of the coordinator commands: approvals, task submissions, handles and receipts.

Every file is read once, bounded, without following a final link, with duplicate keys and
NaN/Infinity refused, and checked against a closed shape before anything is committed. Nothing is
normalized or inferred. An approval is the operator's exact title and script as handed over
(approval-v2, ``native_budget_policy.Approval``); ``start``/``add-clip`` bind it at the
authorization instant, where the transcript itself is checked. The title is always the
operator's exact words: a missing or null title is refused. A task submission names typed tasks
only: no command, argument list or environment.

Approval file (one clip)::

    {"schemaVersion": 1, "kind": "native-short-approval", "clipId": "Q1", "title": "<exact words>",
     "recordedBy": "<who or what recorded it>",
     "script": {"sourceSha256", "sourceSeconds", "transcriptPath", "transcriptSha256", "transcriptWords",
                "wordRanges": [[first, last], ...], "wordTexts": [...], "ranges": [[start, end], ...]}}

Approvals file: ``{"schemaVersion": 1, "kind": "native-short-approvals", "approvals": [<rows as above
without schemaVersion and kind>]}``. Task file: ``{"schemaVersion": 1, "kind":
"native-production-tasks", "tasks": [{"taskId", "kind", "version", "deadlineElapsed",
"inputFingerprint" | "mediaRequest", optional "clipId", "route", "prerequisites", "parent",
"replaces"}]}``; a media task names its ``mediaRequest`` file (``production.media``) instead of a
fingerprint, and its clip and route come from that request.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from studio.native_budget_policy import Approval
from studio.native_budget_selection import script_problem, title_problem
from studio.production.host_contract import require_handle, valid_usage
from studio.production.media import MAX_REQUEST_BYTES, admit_request, parse_json
from studio.native_budget_binding import launch_fingerprint
from studio.production.tasks import TaskSpec

MAX_INPUT_BYTES = 4 * 1024 ** 2
APPROVAL_KEYS = frozenset({'clipId', 'title', 'recordedBy', 'script'})
SCRIPT_KEYS = frozenset({'sourceSha256', 'sourceSeconds', 'transcriptPath', 'transcriptSha256', 'transcriptWords',
                         'wordRanges', 'wordTexts', 'ranges'})
TASK_REQUIRED = frozenset({'taskId', 'kind', 'version', 'deadlineElapsed'})
TASK_OPTIONAL = frozenset({'inputFingerprint', 'mediaRequest', 'clipId', 'route', 'prerequisites', 'parent',
                           'replaces'})


@dataclass(frozen=True)
class Submission:
    """One typed task and, for a media task, its request's exact bytes and input identity (kept by ``enqueue``)."""

    spec: TaskSpec
    request: tuple[bytes, str] | None = None


def read_file(path: Path, limit: int = MAX_INPUT_BYTES) -> bytes:
    """The bytes of one bounded regular file (a final link is not followed)."""
    try:
        file = Path(path).parent.resolve(strict=True) / Path(path).name
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise ValueError(f'{path} cannot be read: {error}') from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(f'{file} is not a regular file of at most {limit} bytes')
        chunks = []
        while chunk := os.read(fd, 1024 ** 2):
            chunks.append(chunk)
        return b''.join(chunks)
    finally:
        os.close(fd)


def _pairs(value: object, name: str) -> tuple[tuple, ...]:
    """A list of [a, b] pairs of numbers (booleans excluded), as tuples."""
    if type(value) is not list or not all(type(row) is list and len(row) == 2 and all(
            type(item) in (int, float) for item in row) for row in value):
        raise ValueError(f'{name} is a list of [first, last] pairs')
    return tuple(tuple(row) for row in value)


def _approval(row: object, where: str) -> tuple[str, Approval]:
    """(clip id, Approval) of one approval row; title and script shapes are checked here, the transcript at bind."""
    if type(row) is not dict or set(row) != APPROVAL_KEYS or type(row['script']) is not dict \
            or set(row['script']) != SCRIPT_KEYS:
        raise ValueError(f'{where}: an approval has exactly clipId, title, recordedBy and script '
                         f'({", ".join(sorted(SCRIPT_KEYS))})')
    script = row['script']
    if type(script['transcriptPath']) is not str or not script['transcriptPath'].startswith('/') \
            or type(script['wordTexts']) is not list:
        raise ValueError(f'{where}: the script names an absolute transcriptPath and the text of every kept word')
    approval = Approval(title=row['title'], source_sha256=script['sourceSha256'],
                        transcript_sha256=script['transcriptSha256'], transcript_words=script['transcriptWords'],
                        transcript_path=script['transcriptPath'], source_seconds=script['sourceSeconds'],
                        word_ranges=_pairs(script['wordRanges'], f'{where}: wordRanges'),
                        word_texts=tuple(script['wordTexts']), ranges=_pairs(script['ranges'], f'{where}: ranges'),
                        recorded_by=row['recordedBy'])
    shape = {**script, 'wordRanges': [list(item) for item in approval.word_ranges],
             'ranges': [list(item) for item in approval.ranges]}
    problem = title_problem(approval.title) or script_problem(shape)
    if problem:
        raise ValueError(f'{where}: {problem}')
    return row['clipId'], approval


def _single(path: Path) -> tuple[str, Approval]:
    """One ``native-short-approval`` file."""
    value = parse_json(read_file(path), str(path))
    if value.get('schemaVersion') != 1 or value.get('kind') != 'native-short-approval':
        raise ValueError(f'{path} is not a native-short-approval file')
    return _approval({key: item for key, item in value.items() if key not in ('schemaVersion', 'kind')}, str(path))


def load_approvals(pairs: list[str], bundle: Path | None, clips: tuple[str, ...]) -> dict | None:
    """The approvals handed over at start (``--approval CLIP=FILE`` repeated, or ``--approvals FILE``), or None."""
    if pairs and bundle is not None:
        raise ValueError('Give the approvals either as --approval CLIP=FILE for each clip or as one --approvals FILE')
    rows = []
    for pair in pairs:
        clip, separator, file = pair.partition('=')
        if not separator or not clip or not file:
            raise ValueError(f'--approval takes CLIP=FILE, not {pair!r}')
        named, approval = _single(Path(file))
        if named != clip:
            raise ValueError(f'{file} approves clip {named!r}, not {clip!r}')
        rows.append((clip, approval))
    if bundle is not None:
        value = parse_json(read_file(bundle), str(bundle))
        if value.get('schemaVersion') != 1 or value.get('kind') != 'native-short-approvals' \
                or type(value.get('approvals')) is not list:
            raise ValueError(f'{bundle} is not a native-short-approvals file')
        rows = [_approval(row, f'{bundle} approval {index}') for index, row in enumerate(value['approvals'])]
    if not rows:
        return None
    approvals = dict(rows)
    if len(approvals) != len(rows) or set(approvals) != set(clips):
        raise ValueError(f'Approvals name every declared clip exactly once ({", ".join(clips)}); '
                         f'given: {", ".join(clip for clip, _ in rows)}')
    return approvals


def load_approval(path: Path, clip_id: str) -> Approval:
    """The approval handed over with a clip added after start."""
    named, approval = _single(path)
    if named != clip_id:
        raise ValueError(f'{path} approves clip {named!r}, not {clip_id!r}')
    return approval


def _task(row: object, batch_id: str, where: str) -> Submission:
    """One typed task row; a media task's request is validated and fingerprinted."""
    if type(row) is not dict or not TASK_REQUIRED <= set(row) or not set(row) <= TASK_REQUIRED | TASK_OPTIONAL \
            or ('mediaRequest' in row) == ('inputFingerprint' in row):
        raise ValueError(f'{where}: a task has {", ".join(sorted(TASK_REQUIRED))} and either inputFingerprint or, '
                         'for media, mediaRequest')
    if (row['kind'] == 'media') != ('mediaRequest' in row):
        raise ValueError(f'{where}: a media task, and only a media task, names its mediaRequest')
    kept, fingerprint = None, row.get('inputFingerprint')
    fields = {'clip_id': row.get('clipId'), 'route': row.get('route')}
    if 'mediaRequest' in row:
        data = read_file(Path(row['mediaRequest']), MAX_REQUEST_BYTES)
        request, request_sha, identity = admit_request(data, row['mediaRequest'])
        if (request['batchId'], request['taskId']) != (batch_id, row['taskId']) \
                or any(row.get(key) not in (None, request[key]) for key in ('clipId', 'route')):
            raise ValueError(f'{where}: the media request names another batch, task, clip or route')
        kept, fields = (data, identity), {'clip_id': request['clipId'], 'route': request['route']}
        fingerprint = launch_fingerprint(request_sha, identity)
    prerequisites = row.get('prerequisites', [])
    if type(prerequisites) is not list:
        raise ValueError(f'{where}: prerequisites is a list of task ids')
    spec = TaskSpec(row['taskId'], batch_id, row['kind'], row['version'], fingerprint, row['deadlineElapsed'],
                    prerequisites=tuple(prerequisites), parent=row.get('parent'), replaces=row.get('replaces'),
                    **fields)
    return Submission(spec, kept)


def load_tasks(path: Path, batch_id: str) -> tuple[Submission, ...]:
    """A ``native-production-tasks`` submission for this batch."""
    value = parse_json(read_file(path), str(path))
    if value.get('schemaVersion') != 1 or value.get('kind') != 'native-production-tasks' \
            or type(value.get('tasks')) is not list or not value['tasks']:
        raise ValueError(f'{path} is not a native-production-tasks file with at least one task')
    return tuple(_task(row, batch_id, f'{path} task {index}') for index, row in enumerate(value['tasks']))


def handle(text: str) -> dict:
    """A JSON process {type, pid, pgid, started} or host {type, host, thread, turn} handle."""
    return require_handle(parse_json(text.encode(), '--handle'))


def usage(text: str | None) -> dict | None:
    """Cumulative host usage as JSON (every token field; null when unknown), or None."""
    if text is None:
        return None
    value = parse_json(text.encode(), '--usage')
    if not valid_usage(value):
        raise ValueError('--usage names inputTokens, outputTokens, cachedInputTokens and reasoningTokens '
                         '(null when unknown; cached input is part of input)')
    return value


def _receipt(path: Path) -> dict:
    """{path, sha256, bytes} of one regular file, hashed here (a final link is not followed)."""
    file = Path(path).parent.resolve(strict=True) / Path(path).name
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle_file:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f'{file} is not a regular file')
        return {'path': str(file), 'sha256': hashlib.file_digest(handle_file, 'sha256').hexdigest(),
                'bytes': info.st_size}


def receipts(paths: list[Path]) -> tuple[dict, ...]:
    """Artifact receipts of regular files, hashed here (a caller's digest is not taken)."""
    return tuple(_receipt(path) for path in paths)
