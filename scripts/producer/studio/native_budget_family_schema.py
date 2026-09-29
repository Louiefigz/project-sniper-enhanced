"""Closed logical Long launches whose bounded children arrive as authors finish.

A family is part of an ordinary counted attempt, not a process or another store.
An awaiting family retains its original deadline and duplicate-launch exclusion;
each invocation separately records actual supervisor liveness and its outcome.
"""
from __future__ import annotations

from pathlib import Path

from studio.native_budget_schema import _attempt_id, _digest, _nonnegative, _row_ok, _text

MAX_FAMILIES = 4
MAX_INVOCATIONS = 12
FAMILY_KEYS = {'id', 'plan', 'sharedPlan', 'assignments', 'previewInventory', 'state', 'invocations'}
INVOCATION_KEYS = {'id', 'sectionId', 'project', 'output', 'planSha256', 'scopeSha256',
                   'requestSha256', 'supervisor', 'status', 'admittedElapsed', 'completedElapsed',
                   'resultStatus', 'resultIdentity', 'failure'}
ASSIGNMENT_KEYS = {'sectionId', 'generation', 'inputIdentity', 'frameRange', 'authorTaskId'}
FAMILY_STATES = {'awaiting-sections', 'finalizing', 'complete', 'failed'}
INVOCATION_STATES = {'running', 'succeeded', 'failed', 'abandoned'}


def pin_ok(pin: object) -> bool:
    """Validate exact bounded references without turning a schema read into filesystem IO."""
    from studio.production.section_results import validate_pin
    try:
        validate_pin(pin)
    except (ValueError, TypeError, KeyError):
        return False
    return _text(pin['path'])


def bounds_ok(value: object) -> bool:
    """One integer half-open absolute frame range."""
    return type(value) is list and len(value) == 2 and all(type(item) is int for item in value) \
        and 0 <= value[0] < value[1]


def assignment_ok(row: object) -> bool:
    """Frozen registered logical ownership, independent from technical encoder windows."""
    from studio.production.task_schema import TASK_ID
    return type(row) is dict and set(row) == ASSIGNMENT_KEYS \
        and all(type(row[key]) is str and TASK_ID.fullmatch(row[key]) is not None
                for key in ('sectionId', 'authorTaskId')) \
        and type(row['generation']) is int and row['generation'] >= 1 \
        and _digest(row['inputIdentity']) and bounds_ok(row['frameRange'])


def invocation_ok(row: object) -> bool:
    """One charged family's child, with exact path ownership and bounded terminal evidence."""
    if type(row) is not dict or set(row) != INVOCATION_KEYS or not _attempt_id(row['id']):
        return False
    if not all(_text(row[key]) and Path(row[key]).is_absolute()
               and '..' not in Path(row[key]).parts for key in ('project', 'output')):
        return False
    if not _digest(row['planSha256']) or not _row_ok('supervisor', row['supervisor']):
        return False
    if any(row[key] is not None and not _digest(row[key])
           for key in ('scopeSha256', 'requestSha256', 'resultIdentity')):
        return False
    if row['status'] not in INVOCATION_STATES or not _nonnegative(row['admittedElapsed']):
        return False
    if (row['status'] == 'running') != (row['completedElapsed'] is None):
        return False
    if row['completedElapsed'] is not None and not _nonnegative(row['completedElapsed']):
        return False
    if row['completedElapsed'] is not None and row['completedElapsed'] < row['admittedElapsed']:
        return False
    if row['resultStatus'] is not None and not _text(row['resultStatus']):
        return False
    if row['status'] == 'succeeded' and not (row['resultStatus'] and _digest(row['resultIdentity'])
                                            and _digest(row['requestSha256'])):
        return False
    if row['status'] == 'running' and any(row[key] is not None for key in ('resultStatus', 'resultIdentity')):
        return False
    if row['status'] in ('failed', 'abandoned'):
        return _row_ok('failure', row['failure'])
    return row['failure'] is None


def preview_ok(inventory: object, assignments: list[dict]) -> bool:
    """Each declared scope owns a fixed ordered list of bounded moving-preview ranges."""
    expected = len(assignments) + (1 if len(assignments) > 1 else 0)
    if type(inventory) is not list or len(inventory) != expected:
        return False
    for item, assignment in zip(inventory, assignments):
        if not preview_row_ok(item, assignment):
            return False
    if len(inventory) == len(assignments) + 1:
        joins = {'sectionId': None, 'frameRange': [0, assignments[-1]['frameRange'][1]]}
        return preview_row_ok(inventory[-1], joins)
    return True


def preview_row_ok(item: object, assignment: dict) -> bool:
    """Preview windows cannot grow past their frozen logical section bounds."""
    if type(item) is not dict or set(item) != {'sectionId', 'frameRange', 'windows'}:
        return False
    if any(item[key] != assignment[key] for key in ('sectionId', 'frameRange')):
        return False
    windows, bounds = item['windows'], item['frameRange']
    return type(windows) is list and 1 <= len(windows) <= 256 and all(bounds_ok(row)
        and bounds[0] <= row[0] < row[1] <= bounds[1] for row in windows) \
        and all(left[1] <= right[0] for left, right in zip(windows, windows[1:]))


def family_ok(row: object, attempts: dict) -> bool:
    """A logical family may only inhabit one actual counted preview or final attempt."""
    if type(row) is not dict or set(row) - {'reviewService'} != FAMILY_KEYS or row['id'] not in attempts:
        return False
    if 'reviewService' in row and not service_ok(row['reviewService']):
        return False
    if attempts[row['id']]['route'] not in ('preview', 'final') or row['state'] not in FAMILY_STATES:
        return False
    if not pin_ok(row['plan']) or not pin_ok(row['sharedPlan']):
        return False
    assignments = row['assignments']
    if type(assignments) is not list or not 1 <= len(assignments) <= 3 or not all(map(assignment_ok, assignments)):
        return False
    ids = {item['sectionId'] for item in assignments}
    if len(ids) != len(assignments) or not preview_ok(row['previewInventory'], assignments):
        return False
    if assignments[0]['frameRange'][0] != 0 or any(left['frameRange'][1] != right['frameRange'][0]
            for left, right in zip(assignments, assignments[1:])):
        return False
    invocations = row['invocations']
    if type(invocations) is not list or len(invocations) > MAX_INVOCATIONS or not all(map(invocation_ok, invocations)):
        return False
    if any(item['sectionId'] is not None and item['sectionId'] not in ids for item in invocations):
        return False
    if len({item['id'] for item in invocations}) != len(invocations):
        return False
    if len({item['output'] for item in invocations}) != len(invocations):
        return False
    active = [item['sectionId'] for item in invocations if item['status'] == 'running']
    if (row['state'] in ('awaiting-sections', 'finalizing')) != (attempts[row['id']]['status'] == 'running'):
        return False
    return len(set(active)) == len(active) and (None not in active or len(active) == 1)


def service_ok(value: object) -> bool:
    """An optional operational pin is not media identity or filesystem read authority."""
    return type(value) is dict and set(value) == {'schemaVersion', 'envelope'} \
        and type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and pin_ok(value['envelope'])


def family_problem(record: dict) -> str | None:
    """Refuse unversioned, duplicated or malformed family authority on every read."""
    for clip in record['clips'].values():
        rows = clip.get('sectionFamilies', [])
        if record['schemaVersion'] < 7 and 'sectionFamilies' in clip:
            return 'section families require schema 7'
        if rows and clip.get('output', {}).get('format') != 'long':
            return 'section families require an authorized Long'
        attempts = {row['id']: row for row in clip['attempts']}
        if type(rows) is not list or len(rows) > MAX_FAMILIES or not all(family_ok(row, attempts) for row in rows):
            return 'invalid section family history'
        if len({row['id'] for row in rows}) != len(rows):
            return 'duplicate section family id'
    return None
