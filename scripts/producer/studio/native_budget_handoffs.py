"""Visible hand-off evidence for batch status: the one seam, ``handoff_verdicts``.

Two sources, judged apart:

- The authority trail. Each ``clip-handed-off`` event that ``native_batch.py handoff`` (unit A3)
  records carries A3's summary ``{record, confirmation, mp4, viewsVerifiedAt, visibleHandoffAt}``,
  where ``record`` and ``confirmation`` are ``{path, sha256}`` bindings (anything else, a bare
  truthy value included, is rejected). It is judged by the event's own batch-clock ``elapsed``:
  the hand-off was visible no later than that. The confirmation's wall-clock stamps are display
  only: reported beside it as written, never converted and never a reason to reject it (a wall
  clock can step back; a stamp later than this observation is flagged ``wallAheadOfObservation``).
  Only this source meets the SLA.
- Files named with ``status --handoff``, checked by the shared reader
  ``studio.production.handoff.verified_handoff`` (unit A3, imported at run time; without it a file
  is rejected and never visible). They are not on the batch clock: a visible-handoff file shows the
  hand-off happened but never meets the SLA until ``native_batch.py handoff`` records it.

Only a ``visible-handoff`` confirmation is visible; a views-ready record verifies the matching
Studio view server-side. The approved-content comparison unit B3 wrote into the bound views-ready
record (``content``) is read from that record while its bytes still match the binding.
"""
from __future__ import annotations

import importlib
import math
import re
from pathlib import Path

from studio.native_budget_evidence import (
    WALL, EvidenceRejected, delivery_summary, mapping, read_record, require, wall_stamps,
)
from studio.native_handoff_content import MATERIAL  # P0 Step 4.3: the content fields src's hand-off checks

HANDOFF_READER = 'studio.production.handoff'
READER_MISSING = 'the hand-off evidence reader (studio.production.handoff, unit A3) is not in this engine'
LEVELS = ('visible-handoff', 'views-ready')
SHA256 = re.compile(r'[0-9a-f]{64}')
TRAIL = 'batch clock (the recorded clip-handed-off event)'


def handoff_reader() -> object | None:
    """The shared hand-off check (unit A3), or None when this engine does not have it."""
    try:
        return importlib.import_module(HANDOFF_READER)
    except ModuleNotFoundError as error:
        if error.name != HANDOFF_READER:
            raise
        return None


def binding(value: object, name: str) -> dict:
    """An exact ``{path, sha256}`` binding."""
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'} and isinstance(value['path'], str)
            and isinstance(value['sha256'], str) and SHA256.fullmatch(value['sha256']) is not None,
            f'the hand-off {name} is not a {{path, sha256}} binding')
    return {'path': value['path'], 'sha256': value['sha256']}


def content_summary(bound: dict) -> dict:
    """B3's approved-content comparison from the bound views-ready record, if its bytes still match."""
    try:
        value, digest = read_record(Path(bound['path']))
    except (EvidenceRejected, OSError, ValueError) as error:
        return {'status': 'unavailable', 'reason': f'{type(error).__name__}: {error}'[:300]}
    if digest != bound['sha256']:
        return {'status': 'unavailable', 'reason': 'the views-ready record changed after it was bound'}
    content = mapping(value.get('content'))
    return {'status': mapping(content.get('operatorApproval')).get('status'), 'title': content.get('title'),
            **{key: content.get(key) for key in MATERIAL},
            'mismatches': [key for key in MATERIAL if content.get(key) is False],
            'missingWords': content.get('missingWords'), 'extraWords': content.get('extraWords'),
            'displayCorrections': len(content.get('displayCorrections') or [])}


def _stamps(record: dict, summary: dict, visible: bool) -> dict:
    """The display-only wall-clock stamps of this hand-off level, as written and flagged (``wall_stamps``)."""
    names = ('viewsVerifiedAt', 'visibleHandoffAt') if visible else ('viewsVerifiedAt',)
    return wall_stamps(record, {name: summary.get(name) for name in names})


def _trail(record: dict, event: dict, now: float) -> dict:
    """A recorded hand-off bound to the exact delivery of its clip, on the batch clock."""
    clip_id, at, summary = event.get('clipId'), event.get('elapsed'), mapping(event.get('handoff'))
    require(clip_id in record['clips'], f'the recorded hand-off names unknown clip {clip_id!r}')
    require(type(at) in (int, float) and math.isfinite(at) and 0 <= at, 'the hand-off event has no batch time')
    require(at <= now, f'future-dated evidence: the hand-off event at {at:.1f}s is later than this observation')
    record_binding = binding(summary.get('record'), 'record')
    visible = summary.get('confirmation') is not None
    confirmation = binding(summary.get('confirmation'), 'confirmation') if visible else None
    mp4 = mapping(summary.get('mp4'))
    row = next((row for row in reversed(record['clips'][clip_id]['deliveries'])
                if (row['output'], row['sha256']) == (mp4.get('path'), mp4.get('sha256'))), None)
    require(row is not None, f'the recorded hand-off names no delivery of clip {clip_id}')
    require(row['elapsed'] <= at, 'the hand-off was recorded before its MP4 was delivered')
    return {'kind': LEVELS[0] if visible else LEVELS[1], 'source': 'authority trail', 'clock': TRAIL, 'at': at,
            'visibleHandoffAt': at if visible else None, 'wall': _stamps(record, summary, visible),
            'delivery': delivery_summary(record, clip_id, row), 'record': record_binding,
            'confirmation': confirmation, 'content': content_summary(record_binding)}


def trail_verdict(record: dict, event: dict, now: float) -> dict:
    """What one ``clip-handed-off`` event's recorded hand-off establishes."""
    label = f'authority trail: clip-handed-off {event.get("clipId")} at {event.get("elapsed")}'
    try:
        return {'file': label, 'accepted': True, **_trail(record, event, now)}
    except (EvidenceRejected, ValueError) as error:
        return {'file': label, 'accepted': False, 'reason': f'{type(error).__name__}: {error}'[:600]}


def _file(record: dict, evidence: dict) -> dict:
    """A hand-off file the shared reader verified: real, but not on the batch clock."""
    require(evidence.get('level') in LEVELS, f'unknown hand-off level {evidence.get("level")!r}')
    visible = evidence['level'] == LEVELS[0]
    confirmation = binding(evidence.get('confirmation'), 'confirmation') if visible else None
    record_binding = binding(evidence.get('record'), 'record')
    row = evidence['delivery']
    return {'kind': evidence['level'], 'source': 'hand-off file', 'clock': WALL, 'at': None, 'visibleHandoffAt': None,
            'wall': _stamps(record, evidence, visible), 'delivery': delivery_summary(record, row['clipId'], row),
            'record': record_binding, 'confirmation': confirmation, 'content': content_summary(record_binding)}


def file_verdict(record: dict, path: Path) -> dict:
    """A named hand-off file, read by the shared reader against every delivery of this batch."""
    reader = handoff_reader()
    if reader is None:
        return {'file': str(path), 'accepted': False, 'reason': READER_MISSING}
    deliveries = [{**row, 'clipId': clip_id} for clip_id, clip in record['clips'].items() for row in clip['deliveries']]
    try:
        found = _file(record, reader.verified_handoff(path, deliveries))
    except (EvidenceRejected, OSError, ValueError) as error:  # the reader's HandoffEvidenceError is a ValueError
        return {'file': str(path), 'accepted': False, 'reason': f'{type(error).__name__}: {error}'[:600]}
    return {'file': str(path), 'accepted': True, **found}


def handoff_verdicts(record: dict, events: tuple[dict, ...], files: tuple[Path, ...], now: float) -> list[dict]:
    """The one hand-off seam: the trail's recorded hand-offs (observed with the record), then each named file."""
    trail = [trail_verdict(record, event, now) for event in events if event.get('event') == 'clip-handed-off'
             and isinstance(event.get('handoff'), dict)]
    return [*trail, *(file_verdict(record, path) for path in files)]
