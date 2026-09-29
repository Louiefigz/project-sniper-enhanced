"""The authorization block of a batch record: what the operator handed over, and what came before it.

``identity`` is SHA-256 of the batch id, the declared clips, their first approval identities and the
AI slots and reservations; ``content_identity`` is the same without the AI settings, so a rerun that
changes only settings is recognized as the same hand-over. ``setup`` says whether capacity, hashing
and the engine freeze completed after the clock started.

``prior`` lists the earlier authorizations of the same batch id that never became this batch: staged
starts that expired, were replaced by a new hand-over, were discarded by the operator, or whose id
was taken. Each is a miss of its own go time; a fresh clock never hides it. At most ``PRIOR_BOUND``
are kept (the earliest first) and ``priorOmitted`` counts the rest.
"""
from __future__ import annotations

import hashlib
import json

from studio.production.host_contract import encoded_length, finite_seconds

PRIOR_BOUND = 8
CAUSES = ('expired', 'replaced', 'operator', 'taken')
PRIOR_KEYS = {'name', 'authorizedAtEpoch', 'deadlineEpoch', 'discardedAtEpoch', 'cause', 'reason'}
BLOCK_KEYS = {'identity', 'setup', 'setupElapsed', 'prior', 'priorOmitted'}


def _body(record: dict, with_ai: bool) -> str:
    """The canonical JSON the identities hash."""
    declared = sorted(clip_id for clip_id, clip in record['clips'].items() if not clip['addedAfterStart'])
    approvals = [(record['clips'][clip_id]['approvals'] or [{}])[0].get('identity') for clip_id in declared]
    body = {'batchId': record['batchId'], 'clips': declared, 'approvals': approvals}
    if with_ai:
        ai = record['production']['ai']
        body['ai'] = [ai['slots'], ai['reservations']]
    return json.dumps(body, separators=(',', ':'))


def authorization_identity(record: dict) -> str:
    """SHA-256 of what the operator authorized at start: batch, declared clips, their approval identities
    and the AI slots and reservations."""
    return hashlib.sha256(_body(record, True).encode()).hexdigest()


def content_identity(record: dict) -> str:
    """The authorization identity without the AI settings: the batch, its clips and their approved content."""
    return hashlib.sha256(_body(record, False).encode()).hexdigest()


def new_authorization(record: dict) -> dict:
    """A complete authorization with no prior hand-overs (set on the record's production block)."""
    return {'identity': authorization_identity(record), 'setup': 'complete', 'setupElapsed': 0.0, 'prior': [],
            'priorOmitted': 0}


def _epoch(value: object) -> bool:
    """A finite wall-clock time, or None when it cannot be known (another engine's record)."""
    return value is None or finite_seconds(value)


def _prior_ok(row: object) -> bool:
    """One earlier authorization of the same batch id."""
    return type(row) is dict and set(row) == PRIOR_KEYS and type(row['name']) is str \
        and encoded_length(row['name']) <= 96 and _epoch(row['authorizedAtEpoch']) \
        and _epoch(row['deadlineEpoch']) and finite_seconds(row['discardedAtEpoch']) \
        and row['cause'] in CAUSES and type(row['reason']) is str and encoded_length(row['reason']) <= 512


def authorization_problem(record: dict) -> str | None:
    """The authorization minted at start: identity, setup and the earlier hand-overs it replaced."""
    value = record['production']['authorization']
    if type(value) is not dict or set(value) != BLOCK_KEYS or value['setup'] not in ('pending', 'complete') \
            or (value['setupElapsed'] is None) != (value['setup'] == 'pending') \
            or not (value['setupElapsed'] is None or finite_seconds(value['setupElapsed'])):
        return 'authorization record'
    if type(value['prior']) is not list or len(value['prior']) > PRIOR_BOUND \
            or not all(map(_prior_ok, value['prior'])) or type(value['priorOmitted']) is not int \
            or value['priorOmitted'] < 0 or value['priorOmitted'] and len(value['prior']) < PRIOR_BOUND:
        return 'prior authorizations'
    if value['identity'] != authorization_identity(record):
        return 'authorization identity does not match the declared clips and their approvals'
    return None
