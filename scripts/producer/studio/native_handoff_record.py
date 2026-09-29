"""The typed hand-off record: named failures, output/content/project/Studio sections and milestones.

``views-ready`` means every server-side check held: the exact MP4 bytes and receipts, the matching
project unchanged by Studio's load, the registered Studio process live with that MP4 bound and
serving that project, the review player showing the same bytes and label, and no contradiction
with approved content. It is not a visible hand-off: ``visibleHandoffAt`` stays null until the
review player has observed a browser load of the exact MP4 and the interactive coordinator has
attested the Studio page, with ``native_handoff.py confirm`` (``native_handoff_confirm``).
"""
from __future__ import annotations

from datetime import datetime, timezone

from studio.native_handoff_content import mismatches

LIMITATIONS = (
    'Server-side checks only: no browser tab, playback, seeking or listening is verified by this record.',
    'The Studio load is the one Studio performs for its page; later navigation can load more files.',
    'visibleHandoffAt is set only by a later confirmation: an observed review-page load plus the Studio attestation.',
)
CONFIRM = ('open reviewPlayer.url and studio.url for the operator, then native_handoff.py confirm --handoff <this record> '
           '--record <new file> --review-page <reviewPlayer.url> --studio-page <studio.url> --browser <name> '
           '--attested-by <who opened them>')


def utc() -> str:
    """Wall-clock evidence for records."""
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _output_rows(facts: dict) -> list[tuple[str, object]]:
    """Receipts, MP4 bytes, delivered-project bytes and the approved content."""
    before, after, rows = facts['before'], facts['after'], []
    if before['receipts']['verified'] is not True:
        rows.append(('MP4_RECEIPTS_NOT_REVERIFIED_BEFORE_OPEN', before['receipts']['reason']))
    if facts['differs']:
        rows.append(('PROJECT_DIFFERS_FROM_DELIVERY', 'before Studio opened: ' + ', '.join(facts['differs'])))
    if before['receipts']['verified'] is True and after['receipts']['verified'] is not True:
        rows.append(('MP4_RECEIPTS_NOT_REVERIFIED_AFTER_LOAD', after['receipts']['reason']))
    if not after['playable'] or after.get('sha256') != before['sha256']:
        rows.append(('MP4_CHANGED_DURING_HANDOFF', after['label']))
    problem = facts['content']['approvalBinding']['problem']
    if problem:
        rows.append(('APPROVAL_BINDING_MISSING', problem + ': the delivery cannot be matched to its operator-approved '
                     'content (reported, not repaired)'))
    failed = mismatches(facts['content'])
    if failed:
        rows.append(('APPROVED_CONTENT_DIFFERS_FROM_BUILD', ', '.join(failed) + ' is false: the build does not show '
                     'the operator-approved content (reported, not changed)'))
    return rows


def _studio_rows(facts: dict) -> list[tuple[str, object]]:
    """Opening, serving, Studio's effect on the project, and the view's state at record time."""
    studio, view, rows = facts['studio'], facts.get('view') or {}, []
    if not studio['opened']:
        rows.append(('STUDIO_VIEW_OWNED_ELSEWHERE' if studio.get('ownedElsewhere') else 'STUDIO_NOT_OPENED',
                     studio['reason']))
    elif not studio['served']['verified']:
        rows.append(('STUDIO_DID_NOT_SERVE_PROJECT', studio['served']['reason']))
    if facts['changed']:
        code, when = (('STUDIO_CHANGED_PROJECT', 'while Studio opened and served this project') if studio['opened']
                      else ('PROJECT_CHANGED_DURING_HANDOFF', 'during the hand-off, without an open Studio view'))
        rows.append((code, f"{', '.join(facts['changed'])} changed {when}; "
                           f"receipts now: {facts['after']['receipts']['reason'] or 'verified'}"))
    if studio['opened'] and view and view.get('live') is not True:
        rows.append(('STUDIO_NOT_LIVE_AFTER_LOAD', 'the registered Studio process is not live at record time'))
    media = view.get('media') or {}
    if studio['opened'] and view and (media.get('current') is not True or media.get('path') != facts['mp4']['path']):
        rows.append(('STUDIO_NOT_LIVE_AFTER_LOAD', 'the view is not bound to the current delivered MP4 bytes'))
    return rows


def _player_rows(facts: dict) -> list[tuple[str, object]]:
    """The review player serves these bytes and shows the label this hand-off computed after load."""
    player, after = facts['player'], facts['after']
    if not player['verified']:
        return [('REVIEW_PLAYER_NOT_VERIFIED', player['reason'])]
    if (player.get('kind'), player.get('label')) != (after['kind'], after['label']):
        return [('REVIEW_PLAYER_LABEL_DIFFERS', f"the player shows {player.get('label')!r}; after load this "
                                                f"output is {after['label']!r}")]
    return []


def failure_rows(facts: dict) -> list[dict]:
    """Every required hand-off condition that did not hold, each with its plain reason."""
    rows = [*_output_rows(facts), *_studio_rows(facts), *_player_rows(facts), *facts['errors']]
    return [{'code': code, 'message': str(message or '')[:1000]} for code, message in rows]


def compose(facts: dict, request: object) -> dict:
    """The typed record; ``views-ready`` only when every server-side condition held."""
    failures, completed = failure_rows(facts), utc()
    ready = not failures
    output = {**facts['output'], 'mp4': facts['mp4'], 'labelBeforeOpen': facts['before']['label'],
              'pendingFindings': facts['pending'],
              'receipts': {'beforeOpen': facts['before']['receipts'], 'afterLoad': facts['after']['receipts']}}
    project = {'path': str(facts['project']), 'boundFiles': len(facts['bound']),
               'identityBeforeOpen': facts['identityBefore'], 'identityAfterLoad': facts['identityAfter'],
               'differsFromDelivery': facts['differs'], 'changedWhileServed': facts['changed'],
               'unchangedByStudio': not facts['changed'] and facts['identityAfter'] is not None}
    return {'schemaVersion': 1, 'kind': 'native-visible-handoff', 'status': 'views-ready' if ready else 'handoff-incomplete',
            'failures': failures, 'owner': request.owner, 'viewToken': facts['token'], 'attempt': str(request.attempt),
            'output': output, 'content': facts['content'], 'project': project,
            'studio': {**facts['studio'], **(facts.get('view') or {})}, 'reviewPlayer': facts['player'],
            'ownedViews': facts['owned'], 'limitations': list(LIMITATIONS),
            'visibleHandoff': {'status': 'awaiting-operator-page-confirmation' if ready else 'not-available',
                               'confirm': CONFIRM if ready else None},
            'timestamps': {'startedAt': facts['startedAt'], 'studioServedAt': facts['studio'].get('servedAt'),
                           'completedAt': completed, 'viewsVerifiedAt': completed if ready else None,
                           'visibleHandoffAt': None}}


def interrupted(facts: dict, request: object, error: BaseException) -> dict:
    """The record left when a hand-off stops after it may have launched a view, so release can find it."""
    return {'schemaVersion': 1, 'kind': 'native-visible-handoff', 'status': 'handoff-interrupted',
            'failures': [{'code': 'HANDOFF_INTERRUPTED', 'message': f'{type(error).__name__}: {error}'[:1000]}],
            'owner': request.owner, 'viewToken': facts['token'], 'attempt': str(request.attempt),
            'visibleHandoff': {'status': 'not-available', 'confirm': None},
            'timestamps': {'startedAt': facts['startedAt'], 'completedAt': utc(), 'viewsVerifiedAt': None,
                           'visibleHandoffAt': None}}
