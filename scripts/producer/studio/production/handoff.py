"""Hand-off evidence as the batch authority accepts it: the one shared check of unit B3's records.

``native_handoff.py open`` writes a ``native-visible-handoff`` record. Its ``views-ready`` status
means every server-side check held (the exact MP4, the matching project unchanged by Studio, the
served Studio view and the review player); its ``timestamps.visibleHandoffAt`` is always null.
Only ``native_handoff.py confirm`` writes the separate ``native-visible-handoff-confirmation``
record: status ``visible-handoff``, no failures, the review page's own observed playback
(``observed.reviewPagePlayback``), the coordinator's attestation, ``visibleHandoffAt`` and
``handoff`` binding the views-ready record by path and SHA-256.

A confirmation is never accepted on its shape: B3's own verifier must accept it first
(``VERIFIER``: ``studio.native_handoff_confirm.verify_confirmation(path)``, raising when it does
not hold). Until unit B3 provides that function in this engine, every confirmation is refused
("B3 verifier not in this engine"); nothing here re-implements B3's checks. After it, this module
checks what the batch itself needs: the bound record re-hashes, is views-ready with no failures and
names the same view; the confirmation carries observed playback and an attestation; the MP4 it
binds still has that SHA-256 now. ``handoff_evidence(path)`` returns level ``visible-handoff`` for a
confirmation that passes all of it, or ``views-ready`` for a record alone (matching Studio,
server-verified, never visible). ``matching_delivery`` and ``visible_time_problem`` bind it to one
recorded delivery of the clip and to the batch clock. Nothing here opens, plays or approves anything.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from studio.production.host_contract import encoded_length
from studio.production.media import parse_json
from studio.production.settlement import DELIVERY_PATH_BYTES

RECORD, CONFIRMATION = 'native-visible-handoff', 'native-visible-handoff-confirmation'
VISIBLE, VIEWS_READY = 'visible-handoff', 'views-ready'
VERIFIER = ('studio.native_handoff_confirm', 'verify_confirmation')
MAX_RECORD_BYTES = 4 * 1024 ** 2
CLOCK_TOLERANCE_SECONDS = 2.0
# The hand-off's settling line (``clip-handed-off``) carries its evidence paths and times, so both are bounded for
# the trail's reserve (X217 M1): a path to DELIVERY_PATH_BYTES encoded, as a delivery's; a time to these encoded bytes
# (X246 n1: fromisoformat accepts any one character as the separator, an astral one included).
TIME_CHARS = 64


class HandoffEvidenceError(ValueError):
    """The hand-off file is not evidence the authority accepts; the reason names what failed."""


def b3_verifier() -> Callable[[Path], object]:
    """Unit B3's confirmation verifier; refused (never accepted) while it is not in this engine."""
    try:
        verify = getattr(importlib.import_module(VERIFIER[0]), VERIFIER[1], None)
    except ImportError as error:
        raise HandoffEvidenceError(f'B3 verifier not in this engine: {".".join(VERIFIER)} ({error})') from error
    if not callable(verify):
        raise HandoffEvidenceError(f'B3 verifier not in this engine: {".".join(VERIFIER)} is missing')
    return verify


def _read(path: Path, limit: int = MAX_RECORD_BYTES) -> tuple[bytes, dict]:
    """(bytes, {path, sha256}) of one bounded regular file, read without following a final link."""
    try:
        file = Path(path).parent.resolve(strict=True) / Path(path).name
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise HandoffEvidenceError(f'{path} cannot be read: {error}') from error
    if encoded_length(str(file)) > DELIVERY_PATH_BYTES:
        os.close(fd)
        raise HandoffEvidenceError(f'{path} is a path longer than {DELIVERY_PATH_BYTES} encoded bytes')
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise HandoffEvidenceError(f'{file} is not a bounded regular file')
        digest = hashlib.file_digest(handle, 'sha256').hexdigest() if limit > MAX_RECORD_BYTES else None
        data = b'' if digest else handle.read(limit + 1)
    return data, {'path': str(file), 'sha256': digest or hashlib.sha256(data).hexdigest()}


def _json(path: Path) -> tuple[dict, dict]:
    """(value, binding) of one hand-off JSON file."""
    data, binding = _read(path)
    try:
        return parse_json(data, binding['path']), binding
    except ValueError as error:
        raise HandoffEvidenceError(str(error)) from error


def _time(value: object, name: str) -> datetime:
    """An ISO-8601 timestamp with its offset."""
    try:
        moment = datetime.fromisoformat(value) if type(value) is str and encoded_length(value) <= TIME_CHARS else None
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        raise HandoffEvidenceError(f'{name} is not an ISO-8601 time with its offset (at most {TIME_CHARS} encoded '
                                   'bytes)')
    return moment


def _mp4(value: dict) -> dict:
    """The bound MP4: an absolute path and its SHA-256."""
    mp4 = (value.get('output') or {}).get('mp4') if type(value.get('output')) is dict else None
    if type(mp4) is not dict or type(mp4.get('path')) is not str or not mp4['path'].startswith('/') \
            or type(mp4.get('sha256')) is not str or len(mp4['sha256']) != 64:
        raise HandoffEvidenceError('the hand-off record binds no MP4 path and SHA-256')
    return {'path': mp4['path'], 'sha256': mp4['sha256']}


def _views_ready(value: dict, binding: dict) -> dict:
    """A views-ready record with no failures: its MP4, view token and viewsVerifiedAt."""
    if value.get('schemaVersion') != 1 or value.get('kind') != RECORD:
        raise HandoffEvidenceError(f'{binding["path"]} is not a {RECORD} record')
    if value.get('status') != VIEWS_READY or value.get('failures') != []:
        raise HandoffEvidenceError(f'the hand-off is {value.get("status")!r} with failures {value.get("failures")!r}; '
                                   'only a views-ready record with no failures matches Studio')
    timestamps = value.get('timestamps') if type(value.get('timestamps')) is dict else {}
    _time(timestamps.get('viewsVerifiedAt'), 'viewsVerifiedAt')
    if timestamps.get('visibleHandoffAt') is not None:
        raise HandoffEvidenceError('a views-ready record never carries visibleHandoffAt; a confirmation does')
    return {'level': VIEWS_READY, 'record': binding, 'confirmation': None, 'mp4': _mp4(value),
            'viewToken': value.get('viewToken'), 'viewsVerifiedAt': timestamps['viewsVerifiedAt'],
            'visibleHandoffAt': None}


def _observed(value: dict) -> None:
    """The review page's own playback report and the coordinator's attestation are both present."""
    observed, attestation = value.get('observed'), value.get('attestation')
    playback = observed.get('reviewPagePlayback') if type(observed) is dict else None
    if type(playback) is not list or not playback:
        raise HandoffEvidenceError('the confirmation carries no observed review-page playback')
    if type(attestation) is not dict or not all(type(attestation.get(key)) is str and attestation[key].strip()
                                                 for key in ('reviewPage', 'studioPage', 'attestedBy')):
        raise HandoffEvidenceError('the confirmation carries no attestation of the review and Studio pages')


def _confirmed(value: dict, binding: dict) -> dict:
    """A visible-handoff confirmation bound to an unchanged views-ready record."""
    if value.get('schemaVersion') != 1 or value.get('status') != VISIBLE or value.get('failures') != []:
        raise HandoffEvidenceError(f'the confirmation is {value.get("status")!r} with failures '
                                   f'{value.get("failures")!r}; only visible-handoff with no failures is visible')
    bound = value.get('handoff')
    if type(bound) is not dict or type(bound.get('path')) is not str or type(bound.get('sha256')) is not str:
        raise HandoffEvidenceError('the confirmation binds no hand-off record {path, sha256}')
    record, record_binding = _json(Path(bound['path']))
    if record_binding['sha256'] != bound['sha256']:
        raise HandoffEvidenceError(f'the hand-off record {bound["path"]} changed after its confirmation')
    evidence = _views_ready(record, record_binding)
    _observed(value)
    visible = _time(value.get('visibleHandoffAt'), 'visibleHandoffAt')
    verified = _time(evidence['viewsVerifiedAt'], 'viewsVerifiedAt')
    if value.get('viewToken') != evidence['viewToken'] or visible < verified:
        raise HandoffEvidenceError('the confirmation names another view, or confirms before the views were verified')
    return {**evidence, 'level': VISIBLE, 'confirmation': binding, 'visibleHandoffAt': value['visibleHandoffAt']}


def handoff_evidence(path: Path) -> dict:
    """The hand-off level a record or confirmation proves: ``visible-handoff`` or ``views-ready``."""
    value, binding = _json(path)
    if value.get('kind') != CONFIRMATION:
        return _views_ready(value, binding)
    try:
        b3_verifier()(Path(binding['path']))
    except HandoffEvidenceError:
        raise
    except Exception as error:  # B3's verifier refuses in its own terms: never accepted here
        raise HandoffEvidenceError(f'B3\'s verifier refused the confirmation: {type(error).__name__}: {error}') \
            from error
    evidence = _confirmed(value, binding)
    if _read(Path(evidence['mp4']['path']), 64 * 1024 ** 3)[1]['sha256'] != evidence['mp4']['sha256']:
        raise HandoffEvidenceError(f'the MP4 {evidence["mp4"]["path"]} no longer has the bytes the hand-off bound')
    return evidence


def matching_delivery(evidence: dict, deliveries: list[dict]) -> dict:
    """The clip's recorded delivery with exactly the bound MP4 path and SHA-256."""
    mp4 = evidence['mp4']
    for delivery in reversed(deliveries):
        if (delivery['output'], delivery['sha256']) == (mp4['path'], mp4['sha256']):
            return delivery
    raise HandoffEvidenceError(f'the hand-off MP4 {mp4["path"]} ({mp4["sha256"][:12]}…) is not a recorded delivery '
                               'of this clip')


def visible_time_problem(evidence: dict, delivery: dict, clock: tuple[float, float]) -> str | None:
    """Why ``visibleHandoffAt`` lies outside [the delivery's completion on the batch clock, now], or None.

    ``clock`` is (the batch's start epoch, the current epoch).
    """
    start, now = clock
    visible = _time(evidence['visibleHandoffAt'], 'visibleHandoffAt').timestamp()
    if visible - start < delivery['elapsed'] - CLOCK_TOLERANCE_SECONDS:
        return 'visibleHandoffAt precedes the delivery it hands off'
    if visible > now + CLOCK_TOLERANCE_SECONDS:
        return 'visibleHandoffAt lies in the future'
    return None


def verified_handoff(path: Path, deliveries: list[dict]) -> dict:
    """``handoff_evidence`` plus the delivery it matches (``delivery``); raises ``HandoffEvidenceError``."""
    evidence = handoff_evidence(path)
    return {**evidence, 'delivery': matching_delivery(evidence, deliveries)}
