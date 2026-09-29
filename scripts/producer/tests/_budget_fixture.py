"""Shared fixtures for production-budget tests: controllable clocks, private roots, projects."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio import native_budget_clock as clock


@dataclass
class FakeClock:
    """Wall time, boot-continuous time and boot identity that tests move explicitly."""

    wall: float = 1_800_000_000.0
    continuous: float = 5_000.0
    boot: str = '11111111-2222-3333-4444-555555555555'

    def advance(self, seconds: float, wall: float | None = None) -> None:
        """Advance both clocks (optionally moving wall time by a different amount)."""
        self.continuous += seconds
        self.wall += seconds if wall is None else wall

    def reboot(self, downtime: float) -> None:
        """A new boot restarts the continuous clock; wall time moves by the downtime."""
        self.boot = self.boot[:-1] + ('0' if self.boot[-1] != '0' else '1')
        self.continuous = 10.0
        self.wall += downtime


@contextlib.contextmanager
def fake_clock(value: FakeClock) -> Iterator[FakeClock]:
    """Patch every clock the budget code reads."""
    clock.boot_id.cache_clear()
    with mock.patch.object(clock, 'boot_id', lambda: value.boot), \
            mock.patch.object(clock, 'continuous_now', lambda: value.continuous), \
            mock.patch.object(clock.time, 'time', lambda: value.wall):
        yield value


def private_root(test: object) -> Path:
    """A canonical private temporary authority root removed after the test."""
    temporary = tempfile.TemporaryDirectory()
    test.addCleanup(temporary.cleanup)
    base = Path(temporary.name).resolve()
    os.chmod(base, 0o700)
    return base / 'budgets'


SOURCE = b'source-video'
ENGINE = {'root': '/engine', 'identity': 'e' * 64, 'files': 1}


def source_sha(source: bytes = SOURCE) -> str:
    """The digest a batch declares for a TEST recording."""
    return hashlib.sha256(source).hexdigest()


def make_project(parent: Path, name: str, source: bytes = SOURCE,
                 cuts: tuple[tuple[float, float], ...] = ((10.0, 40.0), (50.0, 80.0))) -> Path:
    """A minimal native Short project: one source asset, a 60 s canvas and its source cuts."""
    project = parent / name
    project.mkdir(parents=True)
    sha = source_sha(source)
    plan = {'schemaVersion': 1, 'assets': [{'role': 'source', 'sha256': sha, 'file': f'assets/{sha}.mp4',
                                             'path': str(project / 'assets' / f'{sha}.mp4')}],
            'canvas': {'totalFrames': 1800, 'frameRate': '30/1', 'sourceFile': f'assets/{sha}.mp4',
                       'cuts': [{'start': start, 'end': end, 'speed': 1} for start, end in cuts]}}
    (project / 'SHORT-PROJECT.json').write_text(json.dumps(plan))
    manifest = {'projectHash': hashlib.sha256(name.encode()).hexdigest(), 'files': []}
    (project / 'PROJECT-MANIFEST.json').write_text(json.dumps(manifest))
    return project


RECORDINGS = (b'long-recording-a', b'long-recording-b', b'long-recording-c')


def make_long_project(parent: Path, name: str, recordings: tuple[bytes, ...] = RECORDINGS,
                      request: str = 'request-1', seconds: int = 600) -> Path:
    """A minimal native Long project: LONG-PROJECT.json binding a prepared LONG-REQUEST.json of TEST recordings."""
    directory = parent / 'long-requests' / request
    directory.mkdir(parents=True, exist_ok=True)
    request_file = directory / 'LONG-REQUEST.json'
    if not request_file.exists():
        sources = [{'id': f'source-{index}', 'path': f'/TEST/recordings/{index}.mov', 'sha256': source_sha(data),
                    'sizeBytes': len(data)} for index, data in enumerate(recordings)]
        request_file.write_text(json.dumps({'schemaVersion': 1, 'request': request, 'sources': sources}))
    packet = {'path': str(request_file), 'sha256': hashlib.sha256(request_file.read_bytes()).hexdigest()}
    project = parent / name
    project.mkdir(parents=True)
    plan = {'schemaVersion': 2, 'requestPacket': packet,
            'canvas': {'width': 1920, 'height': 1080, 'frameRate': '30/1', 'totalFrames': seconds * 30}}
    (project / 'LONG-PROJECT.json').write_text(json.dumps(plan))
    return project


# Production tasks (schema version 4). TEST identities only: no real process or host is named.
FINGERPRINT = 'f' * 64
DISPATCHER = {'type': 'process', 'pid': 7001, 'pgid': 7001, 'started': 'Sun Sep 27 10:00:00 2026'}
CHILD = {'type': 'process', 'pid': 7002, 'pgid': 7002, 'started': 'Sun Sep 27 10:00:05 2026'}
DIRECTOR = {'type': 'host', 'host': 'codex', 'thread': 'TEST-thread-director', 'turn': 'TEST-turn-1'}


def host_turn(name: str) -> dict:
    """A TEST host turn handle."""
    return {'type': 'host', 'host': 'codex', 'thread': f'TEST-thread-{name}', 'turn': f'TEST-turn-{name}'}


def table(*handles: dict, survivors: tuple[int, ...] = ()) -> dict:
    """A process table holding exactly these process handles (plus survivors in the given groups)."""
    rows = {1: (0, 1, 'Sun Sep 27 08:00:00 2026')}
    for handle in handles:
        rows[handle['pid']] = (1, handle['pgid'], handle['started'])
    for index, group in enumerate(survivors):
        rows[9000 + index] = (1, group, 'Sun Sep 27 10:30:00 2026')
    return rows


def receipt(name: str, content: bytes = b'TEST artifact') -> dict:
    """An artifact receipt for a TEST file name."""
    return {'path': f'/TEST/artifacts/{name}', 'sha256': hashlib.sha256(content + name.encode()).hexdigest(),
            'bytes': len(content)}


def task_spec(task_id: str, kind: str = 'check', **values: object) -> object:
    """A TaskSpec for batch-auth with a TEST version, fingerprint and a 30-minute deadline."""
    from studio.production.tasks import TaskSpec
    fields = {'run_id': 'batch-auth', 'version': 'v1', 'input_fingerprint': FINGERPRINT, 'deadline_elapsed': 1800.0,
              'clip_id': 'A' if kind in ('author', 'planReview', 'repairCycle', 'media') else None,
              'route': 'draft' if kind == 'media' else None, **values}
    return TaskSpec(task_id, kind=kind, **fields)


APPROVAL_SCRIPTS = {'A': (((10, 39), (50, 79)), ((10.0, 40.0), (50.0, 80.0))),
                    'B': (((300, 339),), ((300.0, 340.0),))}
SOURCE_SECONDS = 2000.0


def transcript_words(count: int = 2000) -> list[dict]:
    """TEST words in the writer's order: word i is 'w<i>' from i to i + 0.9 seconds (a cut [a, b) keeps words a..b-1)."""
    return [{'word': f'w{index}', 'start': float(index), 'end': index + 0.9} for index in range(count)]


def write_transcript(path: Path, words: list[dict]) -> str:
    """Write an utterance transcript (100 words per utterance); return its SHA-256."""
    rows = [{'words': words[start:start + 100]} for start in range(0, len(words), 100)]
    data = json.dumps({'transcript': rows}).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


_TRANSCRIPT: list = []


def shared_transcript() -> tuple[str, str]:
    """(path, SHA-256) of the TEST transcript every TEST approval is bound over (written once per process)."""
    if not _TRANSCRIPT:
        import atexit
        import shutil
        directory = Path(tempfile.mkdtemp(prefix='sniper-budget-transcript-'))
        atexit.register(shutil.rmtree, directory, True)
        path = directory / 'transcript.json'
        _TRANSCRIPT.extend((str(path), write_transcript(path, transcript_words())))
    return _TRANSCRIPT[0], _TRANSCRIPT[1]


CHANGE_REASON = 'TEST operator reason'   # an operator's recorded reason for a change of approved content


def approval(clip: str, title: str | None = None, **changes: object) -> object:
    """A TEST approval: title, in-range word ranges with their texts, and one second range per word range."""
    from dataclasses import replace
    from studio.native_budget_policy import Approval
    offset = 600 + 40 * len(clip)
    word_ranges, seconds = APPROVAL_SCRIPTS.get(clip, (((offset, offset + 29),), ((float(offset), offset + 30.0),)))
    texts = tuple(f'w{index}' for first, last in word_ranges for index in range(first, last + 1))
    path, digest = shared_transcript()
    value = Approval(title=title or f'TEST title {clip}', source_sha256=source_sha(), transcript_sha256=digest,
                     transcript_words=2000, transcript_path=path, source_seconds=SOURCE_SECONDS,
                     word_ranges=word_ranges, word_texts=texts, ranges=seconds, recorded_by='TEST coordinator')
    return replace(value, **changes)


B3_CONFIRMATIONS: set[str] = set()   # SHA-256 of every confirmation this fixture wrote (the stand-in's only accepts)


def _iso(epoch: float) -> str:
    """A UTC ISO-8601 time with its offset."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='milliseconds')


def handoff_confirmation(directory: Path, mp4: tuple[str, str], visible: bool = True, at: float | None = None) -> Path:
    """TEST records in unit B3's shape for one delivered MP4 (path, SHA-256); returns the file ``handoff`` takes.

    A views-ready record and, when ``visible``, the separate confirmation bound to it, confirmed at
    ``at`` (epoch seconds; default now) with observed review-page playback and an attestation. The
    authority accepts none of them by itself: every confirmation is refused until B3's verifier accepts
    it, and tests that hand off install ``b3_stand_in``, which accepts only files written here.
    """
    directory.mkdir(parents=True, exist_ok=True)
    at = time.time() if at is None else at
    record = {'schemaVersion': 1, 'kind': 'native-visible-handoff', 'status': 'views-ready', 'failures': [],
              'owner': 'TEST-owner', 'viewToken': 'TEST-token', 'attempt': str(Path(mp4[0]).parent),
              'output': {'mp4': {'path': mp4[0], 'sha256': mp4[1]}},
              'timestamps': {'startedAt': _iso(at - 3), 'completedAt': _iso(at - 2), 'viewsVerifiedAt': _iso(at - 2),
                             'visibleHandoffAt': None}}
    views = directory / f'handoff-{mp4[1][:8]}.json'
    views.write_text(json.dumps(record))
    if not visible:
        return views
    confirmation = {'schemaVersion': 1, 'kind': 'native-visible-handoff-confirmation', 'status': 'visible-handoff',
                    'failures': [], 'owner': 'TEST-owner', 'viewToken': 'TEST-token',
                    'handoff': {'path': str(views.resolve()), 'sha256': hashlib.sha256(views.read_bytes()).hexdigest()},
                    'observed': {'reviewPagePlayback': [{'event': 'playing', 'route': '/TEST', 'token': 'TEST-page',
                                                         'time': _iso(at - 1)}], 'mediaRequested': []},
                    'attestation': {'reviewPage': 'http://127.0.0.1:1/TEST', 'studioPage': 'http://127.0.0.1:2/TEST',
                                    'browser': 'TEST browser', 'attestedBy': 'TEST coordinator'},
                    'confirmedAt': _iso(at), 'visibleHandoffAt': _iso(at)}
    confirmed = directory / f'confirmation-{mp4[1][:8]}.json'
    confirmed.write_text(json.dumps(confirmation))
    B3_CONFIRMATIONS.add(hashlib.sha256(confirmed.read_bytes()).hexdigest())
    return confirmed


def b3_stand_in_verify(path: Path) -> None:
    """TEST stand-in for unit B3's ``verify_confirmation``: accepts only confirmations this fixture wrote."""
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() not in B3_CONFIRMATIONS:
        raise ValueError('TEST B3 stand-in: not a confirmation the fixture wrote')


def b3_stand_in() -> contextlib.AbstractContextManager:
    """Install the TEST stand-in as B3's verifier (the engine has none: without this, every hand-off is refused)."""
    from studio.production import handoff
    return mock.patch.object(handoff, 'b3_verifier', return_value=b3_stand_in_verify)


def test_mp4(directory: Path, name: str = 'draft.mp4') -> tuple[str, str]:
    """A real TEST MP4 file (the hand-off re-hashes it): (canonical path, SHA-256)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory.resolve() / name
    path.write_bytes(b'TEST mp4 ' + name.encode())
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()
