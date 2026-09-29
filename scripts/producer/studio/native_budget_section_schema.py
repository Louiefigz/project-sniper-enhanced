"""Closed media-owner rows in the existing production-budget authority, schema 6."""
from __future__ import annotations

from studio.native_budget_schema import LIMITS, _attempt_id, _digest, _nonnegative, _row_ok, _text

MAX_SECTION_OWNERS = 768 * (LIMITS['pictureGeneration'] + LIMITS['transientRetry'])
FIELDS = {'id', 'phase', 'inputIdentity', 'planIdentity', 'attemptId', 'output', 'supervisor',
          'admittedElapsed', 'completedElapsed', 'status', 'failure', 'picture', 'retryOf'}
STATES = {'running', 'succeeded', 'failed', 'abandoned'}


def valid_owner(row: object) -> bool:
    """Require bounded identities, process ownership and terminal evidence."""
    if type(row) is not dict or set(row) != FIELDS:
        return False
    if not all(_attempt_id(row[key]) for key in ('id', 'attemptId')):
        return False
    if not all(_digest(row[key]) for key in ('inputIdentity', 'planIdentity')):
        return False
    if not all(_text(row[key]) and row[key] for key in ('phase', 'output')):
        return False
    if not _row_ok('supervisor', row['supervisor']) or not _nonnegative(row['admittedElapsed']):
        return False
    if row['status'] not in STATES or type(row['picture']) is not bool:
        return False
    if row['retryOf'] is not None and not _attempt_id(row['retryOf']):
        return False
    if (row['status'] == 'running') != (row['completedElapsed'] is None):
        return False
    if row['completedElapsed'] is not None and not _nonnegative(row['completedElapsed']):
        return False
    if row['status'] in ('failed', 'abandoned'):
        return _row_ok('failure', row['failure'])
    return row['failure'] is None


def section_problem(record: dict) -> str | None:
    """Validate additive history and forbid unversioned section data in schema 5."""
    for clip in record['clips'].values():
        if type(clip) is not dict:
            return 'invalid clip'
        rows = clip.get('sectionOwners', [])
        if record['schemaVersion'] == 5 and 'sectionOwners' in clip:
            return 'section owners require schema 6'
        if type(rows) is not list or len(rows) > MAX_SECTION_OWNERS or not all(map(valid_owner, rows)):
            return 'invalid section owner history'
        if len({row['id'] for row in rows}) != len(rows):
            return 'duplicate section owner id'
        attempts = {row['id'] for row in clip['attempts']}
        if any(row['attemptId'] not in attempts for row in rows):
            return 'section owner references absent export attempt'
    return None
