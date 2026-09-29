"""``native_handoff.py open``: bind one delivered output, open and load its Studio view, write the record.

Everything the record binds is read before any view opens, so a refusal opens nothing: the
playable MP4, the record and intent paths, the delivery's findings, pending findings, the approved
content from the batch authority and the project identity. Then an O_EXCL intent file (owner, token,
attempt, record) is written; from here on a record carrying this hand-off's token is always
written, including ``handoff-interrupted`` when an exception or SIGTERM (``native_handoff.py``)
stops the command, and the intent file itself lets ``release``/``prune-holds`` find the view if the
process is killed outright. The owned open then launches or reuses and holds the view; the
post-open steps are guarded so an unreadable step becomes a named failure row.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from cut_preview_io import bound_json, write_new
from studio import managed_preview as managed
from studio import managed_preview_owned as owned
from studio import managed_preview_registry as registry
from studio import native_handoff_checks as checks
from studio import native_handoff_content as content
from studio import native_handoff_evidence as evidence
from studio.native_handoff_record import compose, interrupted, utc

VIEW_ERRORS = (RuntimeError, ValueError, OSError)  # StudioServerError and LockBusy are RuntimeErrors
PRODUCTION_KEYS = ('batchId', 'clipId', 'attemptId', 'route')
INTENT_KIND = 'native-visible-handoff-intent'


@dataclass(frozen=True)
class HandoffRequest:
    """One output's hand-off: what to show, who owns the views, where the record goes."""

    attempt: Path
    record: Path
    owner: str
    player: str | None = None
    pending: Path | None = None
    load_seconds: float = checks.DEFAULT_LOAD_SECONDS
    wait_seconds: float = managed.DEFAULT_WAIT_SECONDS


def intent_path(record: Path) -> Path:
    """The O_EXCL intent file beside a record."""
    return record.with_name(record.name + '.intent.json')


def open_studio(project: Path, owner: registry.ViewOwner, mp4: Path, request: HandoffRequest) -> dict:
    """Open or reuse this project's managed view bound to the MP4, then load it as Studio's page does."""
    try:
        record, launched = managed.open_view(str(project), owner, mp4, request.wait_seconds)
    except VIEW_ERRORS as error:
        return {'opened': False, 'reason': f'{type(error).__name__}: {error}'[:600],
                'ownedElsewhere': isinstance(error, registry.ViewOwnedElsewhere),
                'served': {'verified': False, 'reason': 'Studio did not open'}}
    served = checks.studio_served(str(project), record, request.load_seconds)
    return {'opened': True, 'url': record.url, 'port': record.port, 'pid': record.pid,
            'ownership': 'launched-by-this-handoff' if launched else 'reused-and-held-by-this-handoff',
            'served': served, 'servedAt': utc() if served['verified'] else None}


def view_state(project: Path, owner: registry.ViewOwner, request: HandoffRequest) -> dict:
    """The registered view after the load: live identity, bound MP4, holders and who may stop it."""
    status = managed.preview_status(str(project), request.wait_seconds)
    entry = status['preview'] or {}
    others = [row for row in entry.get('heldBy', []) if row.get('token') != owner.token]
    return {'registryState': entry.get('state', 'not-registered'), 'live': status['live'],
            'viewOwner': entry.get('owner'), 'processStarted': (entry.get('identity') or {}).get('started'),
            'media': status['media'], 'cleanup': {
                'state': entry.get('state', 'not-registered'),
                'launchedByThisHandoff': entry.get('ownerToken') == owner.token, 'heldByOthers': others,
                'retainedProcesses': len(entry.get('processes', [])),
                'release': 'native_handoff.py release --handoff <this record> --record <new file>'}}


def guarded(facts: dict, code: str, action: Callable[[], object]) -> object:
    """Run one post-open step; a failure becomes a named row so the record is always written."""
    try:
        return action()
    except VIEW_ERRORS as error:
        facts['errors'].append((code, f'{type(error).__name__}: {error}'))
        return None


def bind_output(request: HandoffRequest, facts: dict) -> Path:
    """Everything the record binds before any view opens; a refusal here opens nothing."""
    before, output_request, project = evidence.delivered(request.attempt)
    evidence.admit_record(request.record, (request.attempt, project))
    evidence.admit_record(intent_path(request.record), (request.attempt, project))
    delivery = bound_json(request.attempt / 'delivery.json')
    production = output_request.get('productionBudget')
    bound = evidence.bound_files(project, output_request)
    facts.update(before=before, delivery=delivery, project=project, bound=bound,
                 findings=evidence.open_findings(delivery), mp4=evidence.mp4_binding(before, delivery),
                 pending=evidence.pending_findings(request.pending),
                 content=content.section(project, production and {key: production.get(key) for key in PRODUCTION_KEYS}))
    facts['identityBefore'] = evidence.identity(project, bound)
    facts['differs'] = evidence.differs_from_delivery(bound, facts['identityBefore'])
    return project


def write_intent(request: HandoffRequest, owner: registry.ViewOwner, facts: dict) -> None:
    """The O_EXCL statement that this token may launch a view, written before the open."""
    write_new(intent_path(request.record), {'schemaVersion': 1, 'kind': INTENT_KIND, 'owner': owner.tag,
                                            'viewToken': owner.token, 'attempt': str(request.attempt),
                                            'record': str(request.record), 'startedAt': facts['startedAt']})
    facts['openAttempted'] = True


def gather(request: HandoffRequest, owner: registry.ViewOwner, facts: dict) -> None:
    """Bind the output, open and load its project, then re-measure everything the record reports."""
    project = bind_output(request, facts)
    write_intent(request, owner, facts)
    facts['studio'] = open_studio(project, owner, Path(facts['before']['file']), request)
    facts['identityAfter'] = guarded(facts, 'PROJECT_IDENTITY_UNREADABLE_AFTER_LOAD',
                                     lambda: evidence.identity(project, facts['bound']))
    facts['changed'] = evidence.changed(facts['identityBefore'], facts['identityAfter']) if facts['identityAfter'] else []
    facts['after'] = evidence.evaluate(request.attempt)
    facts['output'] = evidence.output_state(facts['after'], facts['delivery'], facts['findings'])
    facts['view'] = guarded(facts, 'STUDIO_VIEW_STATE_UNREAD', lambda: view_state(project, owner, request)) \
        if facts['studio']['opened'] else None
    facts['player'] = (checks.player_row(request.player, request.attempt, facts['mp4'], request.load_seconds)
                       if request.player else {'url': None, 'verified': False, 'reason': 'no review-player URL was given'})
    facts['owned'] = guarded(facts, 'OWNED_VIEWS_UNREAD', lambda: owned.owned_views(owner.tag, request.wait_seconds))


def hand_off(request: HandoffRequest) -> dict:
    """Write and return one output's typed record; views stay open for the operator."""
    request = replace(request, attempt=evidence.attempt_folder(str(request.attempt)),
                      record=request.record.absolute(), owner=registry.owner_tag(request.owner))
    owner = registry.ViewOwner(request.owner, secrets.token_hex(16),
                               (str(intent_path(request.record)), str(request.record)))
    facts = {'startedAt': utc(), 'token': owner.token, 'errors': []}
    try:
        gather(request, owner, facts)
        record = compose(facts, request)
    except BaseException as error:
        if facts.get('openAttempted'):
            write_new(request.record, interrupted(facts, request, error))
        raise
    write_new(request.record, record)
    return record
