"""In-memory TEST batch records, launches, tasks and milestone evidence for the status report tests.

Nothing here touches the live budget authority, the host pool or a real host: records are built
in memory on a fake clock, launches are TEST rows, recorded hand-offs are TEST trail events in the
shape ``native_batch.py handoff`` (unit A3) writes, and views-ready and final-review records are TEST
files shaped like units B3 and B2 write them.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from _budget_fixture import FINGERPRINT, FakeClock, approval, fake_clock, source_sha, task_spec
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.production import callbacks, claims, tasks

BATCH = 'batch-auth'
START = FakeClock().wall
PACKET = 'e' * 64          # the TEST final-critic role packet's SHA-256
ALIVE = {'pid': 4242, 'pgid': 4242, 'started': 'Sun Sep 27 09:00:00 2026'}
DISPATCHER = {'type': 'process', 'pid': 7001, 'pgid': 7001, 'started': 'Sun Sep 27 10:00:00 2026'}


def batch_record(clips: tuple[str, ...] = ('A', 'B'), slots: int = 3) -> dict:
    """A TEST batch started at START with a completed setup and each clip's approved title and script."""
    approvals = {clip: approval(clip) for clip in clips}
    with fake_clock(FakeClock()):
        return new_batch_record(BatchSpec(BATCH, clips, (source_sha(),), slots, approvals=approvals), start_anchor())


def iso(elapsed: float) -> str:
    """The UTC wall time ``elapsed`` seconds after the batch start, as B2/B3 records write it."""
    return datetime.fromtimestamp(START + elapsed, timezone.utc).isoformat(timespec='milliseconds')


def attempt(route: str, admitted: float, completed: float | None = None, **fields: object) -> dict:
    """A launch row as the authority records it (``status`` defaults to succeeded; any field may be given)."""
    status = fields.get('status', 'succeeded')
    failure = {'category': 'renderer-failure', 'phase': None, 'errorType': 'RuntimeError', 'signature': 'TEST'}
    row = {'id': uuid.uuid4().hex, 'route': route, 'project': '/TEST/project', 'output': '/TEST/attempt',
           'identity': 'a' * 64, 'admittedElapsed': admitted, 'outputSeconds': 60.0, 'grantedSeconds': 1500.0,
           'supervisor': dict(ALIVE), 'status': status, 'resultStatus': None,
           'failure': failure if status in ('failed', 'abandoned') else None,
           'completedElapsed': completed if status != 'running' else None, 'stages': [], 'nested': {},
           'transientRetryOf': None}
    return {**row, **fields}


def deliver(record: dict, clip_id: str, launch: dict, mp4: tuple[str, str]) -> dict:
    """Record a launch that produced a complete MP4 (a media receipt only)."""
    clip = record['clips'][clip_id]
    clip['attempts'].append(launch)
    row = {'kind': 'final' if launch['route'] in ('final', 'promote') else 'draft', 'output': mp4[0],
           'sha256': mp4[1], 'attemptId': launch['id'], 'elapsed': launch['completedElapsed']}
    clip['deliveries'].append(row)
    return row


def mp4(name: str) -> tuple[str, str]:
    """A TEST MP4 path and digest."""
    return f'/TEST/{name}/review.mp4', hashlib.sha256(name.encode()).hexdigest()


def write_json(directory: Path, name: str, value: dict) -> tuple[Path, str]:
    """Write a TEST record; return its path and SHA-256."""
    data = json.dumps(value).encode()
    path = directory / name
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def observe(record: dict, elapsed: float) -> dict:
    """Move the record's clock anchor to a status observation at this elapsed time (wall = START + elapsed)."""
    record['clock'].update(epoch=START + elapsed, elapsed=elapsed)
    return record


def views_record(directory: Path, video: tuple[str, str], content: dict | None = None) -> dict:
    """A unit-B3 views-ready record with its approved-content comparison; returns its {path, sha256} binding."""
    content = content or {'operatorApproval': {'status': 'supplied'}, 'title': 'exact', 'titleMatchesApproval': True,
                          'sourceMatchesApproval': True, 'wordsMatchApproval': True, 'wordTextsMatchApproval': True,
                          'clipMatchesApproval': True, 'missingWords': [], 'extraWords': [], 'displayCorrections': []}
    value = {'schemaVersion': 1, 'kind': 'native-visible-handoff', 'status': 'views-ready', 'failures': [],
             'output': {'mp4': {'path': video[0], 'sha256': video[1]}}, 'content': content}
    path, digest = write_json(directory, f'views-{video[1][:8]}.json', value)
    return {'path': str(path), 'sha256': digest}


def handoff_summary(video: tuple[str, str], times: tuple[float, float | None], bound: dict | None = None) -> dict:
    """The hand-off summary ``native_batch.py handoff`` (unit A3) records; times = (views verified, visible or None)."""
    verified, visible = times
    return {'record': bound or {'path': '/TEST/handoff.json', 'sha256': 'c' * 64},
            'confirmation': {'path': '/TEST/confirm.json', 'sha256': 'd' * 64} if visible is not None else None,
            'mp4': {'path': video[0], 'sha256': video[1]}, 'viewsVerifiedAt': iso(verified),
            'visibleHandoffAt': iso(visible) if visible is not None else None}


def handed_off(clip: str, summary: dict, at: float) -> dict:
    """A ``clip-handed-off`` trail event recorded at this batch time."""
    return {'event': 'clip-handed-off', 'clipId': clip, 'elapsed': at, 'handoff': summary}


def final_review(submitted: float, clip_id: str = 'A', **timing: object) -> dict:
    """A FINAL-REVIEW record reduced to what the status report reads beside check-final: its schema-2 submission
    (I-B123 7480766d shape), timed on the batch clock from a resolution 120 s before the submission."""
    clock = {'basis': 'batch-authority', 'batchId': BATCH, 'clipId': clip_id, 'resolvedElapsed': submitted - 120,
             'submittedElapsed': submitted, **timing}
    return {'schemaVersion': 2, 'scope': 'native-short-rendered-review',
            'submission': {'schemaVersion': 2, 'role': 'final-critic',
                           'rolePacket': {'path': '/TEST/final-critic-packet.json', 'sha256': PACKET},
                           'packetResolvedAt': iso(submitted - 120), 'submittedAt': iso(submitted),
                           'authenticity': 'declared-not-authenticated', 'timing': clock}}


def packet_resolved(clip_id: str, elapsed: float, role: str = 'final-critic', sha256: str | None = None) -> dict:
    """The trail's packet-resolved event (``studio.production.packets``, I-B123 7480766d shape)."""
    return {'event': 'packet-resolved', 'clipId': clip_id, 'role': role, 'packetSha256': sha256 or PACKET,
            'elapsed': elapsed}


def approved_content(record: dict, clip_id: str, **changes: object) -> dict:
    """The approvedContent block check-final reports (B2 shape), answering this batch's approval of the clip."""
    approval = record['clips'][clip_id]['approvals'][0]
    given = {'batch': record['batchId'], 'clip': clip_id, 'origin': 'studio.production.api.read_approval',
             'identity': approval['identity'], 'scriptSha256': approval['script'], 'title': approval['title']}
    return {'approved': {**given, **changes}, 'planChecked': True, 'departures': [], 'contradictions': [],
            'proposedChanges': []}


def checked(video: tuple[str, str], record_sha: str, content: dict | None, final: str = 'approved') -> dict:
    """What check-final prints (B2 shape) for a record over this MP4."""
    return {'status': 'recorded-independent-final-pass', 'verdict': 'pass', 'reviewer': 'TEST-critic',
            'video': {'path': video[0], 'sha256': video[1]}, 'editorialFinal': final,
            'missing': [] if final == 'approved' else ['whole-program listening'], 'humanApproved': False,
            'independence': 'reviewer-declared-not-authenticated', 'recordSha256': record_sha,
            'approvedContent': content}


def temporary_directory(test: object) -> Path:
    """A canonical (symlink-free) temporary directory removed after the test."""
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    return Path(directory.name).resolve()


def enroll(record: dict, elapsed: float = 1.0) -> None:
    """Enroll the TEST Codex director."""
    director = {'type': 'host', 'host': 'codex', 'thread': 'TEST-thread-director', 'turn': 'TEST-turn-director'}
    claims.enroll_director(record, claims.Enrollment('director', director, 'v1', FINGERPRINT), elapsed)


def run_task(record: dict, spec_args: tuple, handle: dict | None, elapsed: tuple[float, float | None]) -> dict:
    """Enqueue at elapsed[0], claim/attach then, and complete at elapsed[1] (None: still running)."""
    task_id, kind, values = spec_args
    parent = {'parent': 'director'} if kind != 'check' else {}
    tasks.enqueue(record, (task_spec(task_id, kind, **{**parent, **values}),), elapsed[0])
    outcome = claims.claim(record, task_id, DISPATCHER, elapsed[0])
    ref = claims.ClaimRef(task_id, outcome.detail['epoch'], outcome.detail['token'])
    if handle is not None:
        claims.attach(record, ref, handle, elapsed[0])
    if elapsed[1] is not None:
        receipts = (('/TEST/out', task_id),)
        rows = tuple({'path': f'{path}/{name}', 'sha256': hashlib.sha256(name.encode()).hexdigest(), 'bytes': 1}
                     for path, name in receipts)
        callbacks.complete(record, ref, callbacks.TaskResult(rows), elapsed[1])
    return record['production']['tasks'][task_id]


def usage(inputs: int | None, cached: int | None, output: int | None, reasoning: int | None = 0) -> dict:
    """Host-contract usage counts (None = unknown)."""
    return {'inputTokens': inputs, 'cachedInputTokens': cached, 'outputTokens': output, 'reasoningTokens': reasoning}


def record_usage(record: dict, task_id: str, value: dict, elapsed: float) -> None:
    """Report a task's cumulative usage through its current claim."""
    claim = record['production']['tasks'][task_id]['claim']
    callbacks.record_usage(record, claims.ClaimRef(task_id, claim['epoch'], claim['token']), value, elapsed)
