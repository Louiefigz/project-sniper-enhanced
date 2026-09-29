"""Settlement room: everything that may still be recorded after new work stops, at its widest.

``BatchSession.commit`` refuses any change that is not itself a settlement (``TERMINAL_EVENTS``)
or a read-only observation unless the record leaves this room, parallel to the event trail's
reserve. The room covers, each measured on the canonical encoding (escapes counted), not estimated:

- every open task growing to the widest valid task row when it settles;
- every completed task being superseded once (state, retained reason, time, replacement);
- every running launch recording its outcome: the writer (``launch_outcome``) bounds the stages
  and texts in encoded bytes, and a delivered path longer than ``DELIVERY_PATH_BYTES`` is refused,
  never cut;
- every running technical section owner recording its bounded terminal failure;
- the batch's own close, drain, hand-offs and clock observations.

So filling the record with other work (approvals, clips, bindings, launches) can never block a
task outcome, a launch outcome, a supersession or the close. Known limit: an ``abandoned`` launch
(its supervisor was observed gone by exact identity) is not reserved; if its outcome still arrives
it is recorded when it fits.
"""
from __future__ import annotations

import json

from studio.native_budget_schema import AI_POLICY, BOUNDS, ROUTES
from studio.production.formats import output_format
from studio.production.host_contract import HOSTS, MAX_COUNT, MAX_PID, clip_text, encoded_length
from studio.production.task_schema import MAX_TASK_OWNERS, TASK_KINDS, TASK_STATES, settled

WIDE_FLOAT = 1.2345678901234567e-300      # a valid seconds value with the longest float encoding (23 bytes)
NEGATIVE_WIDE = -WIDE_FLOAT               # the longest encoding of any finite float (24 bytes)
STAGE_TEXT_BYTES = 64                     # a launch stage's phase and status
RESULT_TEXT_BYTES = 128                   # a launch's result status, failure category, phase and error type
SIGNATURE_CHARS = 240                     # native_budget_launch.failure_signature keeps this many characters
DELIVERY_PATH_BYTES = 4096                # a delivered file's path, encoded; longer is refused, never cut
# Exporter results the authority records as a delivery: a checked Short or Long MP4, or a Short review draft.
DELIVERED = ('native-short-checked-for-review', 'native-short-review-draft', 'native-long-checked-for-review')


def encoded(value: object) -> int:
    """Bytes a value occupies in the authority's canonical JSON (store.canonical, without its newline)."""
    return len(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False))


def widest_task_row() -> dict:
    """A task row with every field at its bound: the worst case of the canonical encoding.

    Texts are bounded in encoded bytes (escapes counted), integers by MAX_COUNT, floats by
    their longest encoding, so this row is at least as large as any valid row.
    """
    ident, handle = 'T' * 64, {'type': 'host', 'host': max(HOSTS, key=len), 'thread': 'x' * 128, 'turn': 'y' * 128}
    return {'id': ident, 'runId': 'b' * 64, 'clipId': 'C' * 64, 'kind': max(TASK_KINDS, key=len),
            'route': max(ROUTES, key=len), 'version': 'v' * 128, 'inputFingerprint': 'f' * 64,
            'deadlineElapsed': WIDE_FLOAT, 'prerequisites': [f'{index:02d}' + 'T' * 62 for index in range(
                BOUNDS['prerequisites'])], 'parent': ident, 'replaces': ident, 'supersededBy': ident,
            'depth': AI_POLICY['depth'], 'state': max(TASK_STATES, key=len), 'reason': 'r' * 512,
            'enqueuedElapsed': WIDE_FLOAT, 'epochs': MAX_COUNT, 'claim': {
                'epoch': MAX_COUNT, 'token': 'a' * 32, 'claimedElapsed': WIDE_FLOAT, 'claimer': handle,
                'approval': 'a' * 64}, 'handle': handle, 'attempt': 'a' * 32,
            'owners': [{'type': 'process', 'pid': MAX_PID - index, 'pgid': MAX_PID, 'started': 's' * 64}
                       for index in range(MAX_TASK_OWNERS)],
            'receipts': [{'path': 'p' * 1023 + str(index), 'sha256': 'e' * 64, 'bytes': MAX_COUNT}
                         for index in range(8)], 'failure': {'category': 'c' * 64, 'detail': 'd' * 512},
            'unresolved': False, 'charged': False, 'cancelRequested': False, 'endConfirmed': False,
            'usage': {'inputTokens': MAX_COUNT, 'outputTokens': MAX_COUNT, 'cachedInputTokens': MAX_COUNT,
                      'reasoningTokens': MAX_COUNT}, 'terminalElapsed': WIDE_FLOAT, 'approvalStale': False, 'revoked': False}


# One table entry at its widest: the row, its quoted key, the colon and the separating comma.
MAX_TASK_ENTRY_BYTES = encoded(widest_task_row()) + encoded('T' * 64) + 2
WIDEST_OUTCOME = {'status': 'succeeded', 'resultStatus': 'r' * RESULT_TEXT_BYTES, 'completedElapsed': WIDE_FLOAT,
                  'stages': [{'phase': 'p' * STAGE_TEXT_BYTES, 'status': 's' * STAGE_TEXT_BYTES,
                              'elapsedSeconds': NEGATIVE_WIDE}] * BOUNDS['stages'],
                  'failure': {'category': 'c' * RESULT_TEXT_BYTES, 'phase': 'p' * RESULT_TEXT_BYTES,
                              'errorType': 'e' * RESULT_TEXT_BYTES, 'signature': '\U0001F600' * SIGNATURE_CHARS}}
# The delivery row a successful outcome appends, with its separating comma.
DELIVERY_ENTRY_BYTES = encoded({'kind': 'final', 'output': 'o' * DELIVERY_PATH_BYTES, 'sha256': 'e' * 64,
                                'attemptId': 'a' * 32, 'elapsed': WIDE_FLOAT}) + 1


def _text(value: object, limit: int) -> object:
    """A descriptive receipt text cut to ``limit`` encoded bytes; anything else unchanged (the schema judges it)."""
    return clip_text(value, limit) if type(value) is str else value


def _seconds(value: object) -> float | None:
    """A stage's elapsed seconds, rounded to milliseconds; a non-number or one beyond MAX_COUNT is not kept."""
    if type(value) not in (int, float) or not abs(value) <= MAX_COUNT:
        return None
    return round(float(value), 3)


def launch_outcome(result: dict, success: tuple[str, ...]) -> dict:
    """The exporter's receipt fields as the authority records them, within the reserved bounds."""
    outcome = {'status': _text(result.get('status'), RESULT_TEXT_BYTES), 'error': result.get('error'),
               'successStatuses': success, 'stages': [
                   {'phase': _text(row.get('phase'), STAGE_TEXT_BYTES), 'status': _text(row.get('status'),
                                                                                    STAGE_TEXT_BYTES),
                    'elapsedSeconds': _seconds(row.get('elapsedSeconds'))}
                   for row in result.get('stages', [])[:BOUNDS['stages']]]}
    outcome.update({key: _text(result.get(key), RESULT_TEXT_BYTES) for key in ('failureCategory', 'failedPhase',
                                                                              'errorType')})
    if result.get('status') in DELIVERED:  # a checked Short or Long MP4, or a Short review draft
        output = result.get('output')
        if type(output) is str and encoded_length(output) > DELIVERY_PATH_BYTES:
            raise ValueError(f'The delivered path is longer than {DELIVERY_PATH_BYTES} encoded bytes; it is never cut')
        outcome['delivery'] = {'kind': 'final' if result['status'].endswith('for-review') else 'draft',
                               'output': output, 'sha256': result.get('sha256')}
    return outcome


def may_grow(task: dict) -> bool:
    """A task that can still record an outcome: unsettled, or abandoned with an unreported end."""
    return not settled(task) or task['state'] == 'abandoned' and task['handle'] is not None \
        and not task['endConfirmed']


def _open_task_room(task_id: str, task: dict) -> int:
    """An open task growing to the widest row."""
    # Immutable section bindings are already stored; they never shrink settlement room.
    base = {key: value for key, value in task.items() if key != 'sectionBinding'}
    return max(0, MAX_TASK_ENTRY_BYTES - encoded(base) - encoded(task_id) - 2)


def _supersession_room(task: dict) -> int:
    """A completed task superseded once: its state, retained reason, time and replacement."""
    widest = {**task, 'state': 'superseded', 'reason': 'r' * 512, 'terminalElapsed': WIDE_FLOAT,
              'supersededBy': 'T' * 64}
    return max(0, encoded(widest) - encoded(task))


def _outcome_room(attempt: dict) -> int:
    """A running launch recording its widest outcome and delivery."""
    return max(0, encoded({**attempt, **WIDEST_OUTCOME}) - encoded(attempt)) + DELIVERY_ENTRY_BYTES


def _section_owner_room(owner: dict) -> int:
    """A technical window retains its launch evidence and appends its widest bounded outcome."""
    failure = {'category': 'c' * RESULT_TEXT_BYTES, 'phase': owner['phase'],
               'errorType': 'e' * RESULT_TEXT_BYTES, 'signature': '\U0001F600' * SIGNATURE_CHARS}
    widest = {**owner, 'status': 'abandoned', 'completedElapsed': WIDE_FLOAT, 'failure': failure}
    return max(0, encoded(widest) - encoded(owner))


def _review_delivery_room(clip: dict) -> int:
    """Retain one bounded final receipt for each settled section export still awaiting checked delivery."""
    if output_format(clip) != 'long' or not clip.get('sectionOwners'):
        return 0
    delivered = {row['attemptId'] for row in clip['deliveries'] if row['kind'] == 'final'}
    pending = [row for row in clip['attempts'] if row['status'] != 'running' and row['route'] != 'preview'
               and row['id'] not in delivered]
    return len(pending) * DELIVERY_ENTRY_BYTES


def _family_room(family: dict) -> int:
    """Reserve each child outcome without counting its already-retained immutable scope twice."""
    widest = {'status': 'abandoned', 'completedElapsed': WIDE_FLOAT, 'resultIdentity': 'f' * 64,
              'requestSha256': 'f' * 64, 'resultStatus': 'r' * RESULT_TEXT_BYTES,
              'failure': WIDEST_OUTCOME['failure']}
    children = sum(max(0, encoded({**row, **widest}) - encoded(row))
                   for row in family['invocations'] if row['status'] == 'running')
    return children + max(0, len('awaiting-sections') - len(family['state']))


def _lifecycle_room(record: dict) -> int:
    """The batch's close, drain, clip hand-offs and clock observations at their widest."""
    if record['status'] == 'closed':
        return 0
    clock = {'boot': 'b' * 64, 'continuous': NEGATIVE_WIDE, 'epoch': NEGATIVE_WIDE, 'elapsed': WIDE_FLOAT}
    drain = {'startedElapsed': WIDE_FLOAT, 'reason': 'r' * 512}
    handoffs = sum(len('handed-off') - len(clip['state']) for clip in record['clips'].values())
    return max(0, encoded(clock) - encoded(record['clock'])) + max(0, encoded(drain) - encoded(
        record['production']['drain'])) + encoded(WIDE_FLOAT) + len('draining') + max(0, handoffs)


def settlement_reserve(record: dict) -> int:
    """Bytes that settlements, supersessions, launch outcomes and the close may still add."""
    tasks = record['production']['tasks']
    running = [attempt for clip in record['clips'].values() for attempt in clip['attempts']
               if attempt['status'] == 'running']
    return sum(_open_task_room(task_id, task) for task_id, task in tasks.items() if may_grow(task)) \
        + sum(_supersession_room(task) for task in tasks.values() if task['state'] == 'completed') \
        + sum(_outcome_room(attempt) for attempt in running) + _lifecycle_room(record) \
        + sum(_review_delivery_room(clip) for clip in record['clips'].values()) \
        + sum(_family_room(family) for clip in record['clips'].values()
              for family in clip.get('sectionFamilies', [])) \
        + sum(_section_owner_room(owner) for clip in record['clips'].values()
              for owner in clip.get('sectionOwners', []) if owner['status'] == 'running')
