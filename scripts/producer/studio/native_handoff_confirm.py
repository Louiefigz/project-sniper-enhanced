"""Visible hand-off: the served review page's own playback report plus the coordinator's attestation.

A ``views-ready`` record proves servers, not a person's screen, so it never sets ``visibleHandoffAt``
(plan section 5; "a media receipt alone cannot mark visible handoff"). ``confirm`` accepts only a
``views-ready`` record with no failures and its exact verified URLs, then re-runs every check now:
the MP4 bytes and label; the same registered Studio process (pid and start time), live, bound to that
MP4 and serving this project (loaded again, as Studio's page does); the project identity against the
record's post-load identity (checked after that load); the same review-player server (pid, port,
start time) listing this attempt, serving these exact bytes with the after-load label; and, observed
rather than attested, the served review page's own report that its video element started playing this
attempt's exact MP4 route, from a page load (its token) after ``viewsVerifiedAt``
(``review_player_activity``). A bare HTTP request of the MP4, from curl or anything else, is recorded
only as "media requested" and never counts. The attestation states that the review page and the
Studio page were opened for the operator, with the caller's own identity. Only when all of this holds
is ``visibleHandoffAt`` set. What it still cannot prove: that a person watched or listened, that the
window was visible or unobscured, or that playback continued; a local program that fetches the page
can imitate its report. ``verify_confirmation(path)`` re-runs every one of these checks on an existing
confirmation without writing anything (``native_handoff_verify``); the batch authority's ``handoff`` command
calls it before accepting a visible hand-off.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio import managed_preview as managed
from studio import managed_preview_registry as registry
from studio import native_handoff_checks as checks
from studio import native_handoff_evidence as evidence
from studio.native_handoff_record import utc
from studio.native_runtime import digest
from studio.studio_server import ServerRecord

RECHECK_ERRORS = (RuntimeError, ValueError, OSError)
NOT_CLAIMED = ('Not claimed: that a person watched, listened or reviewed; that the window was visible or unobscured; '
               'that playback continued; seeking, listening, editorial or human approval. A page-reported playback '
               'event can be imitated by a local program that fetches the page.')
PLAYBACK_MEANING = ('reviewPagePlayback: the served review page reported its video element playing this exact MP4 '
                    'route (page-load token after viewsVerifiedAt); mediaRequested: HTTP requests of the MP4 from any '
                    'client, never visibility evidence')
KINDS = {'native-visible-handoff', 'native-visible-handoff-intent'}


@dataclass(frozen=True)
class Confirmation:
    """A hand-off record, the new confirmation file, and (review page, Studio page, browser, attested by)."""

    handoff: Path
    record: Path
    pages: tuple[str, str, str, str]
    wait_seconds: float = managed.DEFAULT_WAIT_SECONDS


def read_handoff(file: Path) -> tuple[dict, dict]:
    """A hand-off record (or its intent file) and its exact binding."""
    path = file.resolve(strict=True)
    sha = digest(path)
    value = bound_json(path, sha)
    evidence.require(value.get('kind') in KINDS and value.get('schemaVersion') == 1,
                     f'{path} is not a native hand-off record or intent file')
    return value, {'path': str(path), 'sha256': sha}


def handoff_owner(file: Path) -> dict:
    """The owner claim (tag and token) a hand-off record or intent file carries, for release."""
    value, binding = read_handoff(file)
    return {'owner': registry.view_owner(registry.ViewOwner(value.get('owner'), value.get('viewToken'))),
            'binding': binding}


def _output_rows(value: dict, now: dict) -> list[tuple[str, str]]:
    """The same MP4 bytes and label, and the project identity after this confirmation's own load."""
    output, rows = value['output'], []
    if not now['playable'] or now.get('sha256') != output['mp4']['sha256'] \
            or (now['kind'], now['label']) != (output['reviewState'], output['label']):
        rows.append(('OUTPUT_CHANGED_SINCE_VIEWS_READY', f"now {now['label']!r}"))
    attempt, project = Path(value['attempt']), Path(value['project']['path'])
    bound = evidence.bound_files(project, bound_json(attempt / 'export-request.json'))
    changed = evidence.changed(value['project']['identityAfterLoad'], evidence.identity(project, bound))
    if changed:
        rows.append(('PROJECT_CHANGED_SINCE_VIEWS_READY', ', '.join(changed) + ' changed after the hand-off loaded '
                     'Studio (for example, the operator\'s own Studio navigation stamped more files)'))
    return rows


def _studio_rows(value: dict, status_of: Callable[[str], dict]) -> list[tuple[str, str]]:
    """The same registered Studio process (pid and start), live, bound to the MP4 and serving this project."""
    studio, project = value['studio'], value['project']['path']
    status = status_of(project)
    entry, media = status['preview'] or {}, status['media'] or {}
    identity = entry.get('identity') or {}
    if not (status['live'] and (identity.get('pid'), identity.get('started')) == (studio['pid'], studio['processStarted'])
            and media.get('current') is True and media.get('path') == value['output']['mp4']['path']):
        return [('STUDIO_VIEW_CHANGED_SINCE_VIEWS_READY', 'the verified Studio view is no longer the same live '
                 'registered process (pid and start time) bound to the delivered MP4')]
    served = checks.studio_served(project, ServerRecord(studio['port'], studio['pid'], studio['url'], ''),
                                  checks.DEFAULT_LOAD_SECONDS)
    return [] if served['verified'] else [('STUDIO_NOT_SERVED_AT_CONFIRM', served['reason'])]


def _player_rows(value: dict, now: dict) -> tuple[list[tuple[str, str]], dict]:
    """The verified review-player server still serves these bytes with the after-load label; its request log."""
    recorded, output = value['reviewPlayer'], value['output']
    row = checks.player_row(recorded['url'], Path(value['attempt']), output['mp4'], checks.DEFAULT_LOAD_SECONDS)
    code, expected = 'REVIEW_PLAYER_NOT_VERIFIED_AT_CONFIRM', (output['reviewState'], output['label'])
    if not row['verified']:
        return [(code, f"the review player no longer serves this output: {row['reason']}")], row
    if not recorded.get('server') or row.get('server') != recorded['server'] or row.get('id') != recorded.get('id'):
        return [(code, f"the review player at {recorded['url']} is not the server and row the hand-off verified "
                       f"(was {recorded.get('server')} {recorded.get('id')!r}, now {row.get('server')} {row.get('id')!r})")], row
    if (row.get('kind'), row.get('label')) != expected or (now['kind'], now['label']) != expected:
        return [(code, f"the review player shows {row.get('label')!r}; the after-load evaluation is {expected[1]!r}")], row
    return [], row


def page_playback(row: dict, since: str) -> tuple[list[dict], list[dict]]:
    """The page's own 'playing' reports for this exact route from page loads after ``since``, and the media requests."""
    after = datetime.fromisoformat(since)
    tokens = {page.get('token') for page in row.get('pages', []) if isinstance(page.get('time'), str)
              and datetime.fromisoformat(page['time']) > after}
    activity = row.get('activity') or {}
    playing = [entry for entry in activity.get('playback') or [] if entry.get('event') == 'playing'
               and entry.get('route') == row.get('route') and entry.get('token') in tokens
               and datetime.fromisoformat(entry['time']) > after]
    requested = [entry for entry in activity.get('mediaRequests') or [] if entry.get('path') == row.get('route')
                 and datetime.fromisoformat(entry['time']) > after and not str(entry.get('userAgent')).startswith(checks.TOOL_AGENT)]
    return playing, requested


def recheck(value: dict, status_of: Callable[[str], dict]) -> tuple[list[dict], dict]:
    """Every condition that no longer holds, and what the review page reported; unreadable is a named failure.

    ``status_of(project)`` reads the managed Studio view's state (confirm refreshes it; verification only reads it).
    """
    observed = {'reviewPagePlayback': [], 'mediaRequested': [], 'meaning': PLAYBACK_MEANING}
    try:
        now = evidence.evaluate(Path(value['attempt']))
        rows = _studio_rows(value, status_of) + _output_rows(value, now)
        player, row = _player_rows(value, now)
        playing, requested = page_playback(row, value['timestamps']['viewsVerifiedAt']) if not player else ([], [])
        observed.update(reviewPagePlayback=playing[:20], mediaRequested=requested[:20])
        rows += player + ([] if player or playing else [('REVIEW_PAGE_PLAYBACK_NOT_OBSERVED', 'the served review page '
                          'did not report playing this exact MP4 after the views were verified (a media request alone, '
                          'from curl or any client, is not visibility evidence); open the review page and play it')])
    except RECHECK_ERRORS as error:
        rows = [('CONFIRMATION_RECHECK_FAILED', f'{type(error).__name__}: {error}')]
    return [{'code': code, 'message': str(message)[:1000]} for code, message in rows], observed


def attestation_for(value: dict, pages: tuple[str, str, str, str]) -> dict:
    """The caller's statement, admitted only for a clean views-ready record and its exact verified URLs."""
    review, studio, browser, attested_by = pages
    evidence.require(value.get('kind') == 'native-visible-handoff' and value['status'] == 'views-ready'
                     and value.get('failures') == [],
                     f"only a views-ready hand-off with no failures can become visible; this one is {value.get('status')}")
    evidence.require(review == value['reviewPlayer']['url'] and studio == value['studio']['url'],
                     'the attested pages are not the review-player and Studio URLs this hand-off verified')
    for name, text in (('browser', browser), ('attested-by', attested_by)):
        evidence.require(isinstance(text, str) and 0 < len(text.strip()) <= 120 and '\n' not in text,
                         f'--{name} names who or what (1-120 characters, one line)')
    return {'reviewPage': review, 'studioPage': studio, 'browser': browser, 'attestedBy': attested_by,
            'claims': 'The review page and the Studio page were opened for the operator.', 'notClaimed': NOT_CLAIMED}


def confirm(request: Confirmation) -> dict:
    """Write the confirmation; ``visibleHandoffAt`` is set only when every re-check and the observed load hold."""
    value, binding = read_handoff(request.handoff)
    attestation = attestation_for(value, request.pages)
    record = evidence.admit_record(request.record, (Path(value['attempt']), Path(value['project']['path'])))
    status_of = partial(managed.preview_status, wait_seconds=request.wait_seconds)
    (failures, observed), confirmed = recheck(value, status_of), utc()
    result = {'schemaVersion': 1, 'kind': 'native-visible-handoff-confirmation', 'handoff': binding,
              'owner': value['owner'], 'viewToken': value['viewToken'], 'attestation': attestation,
              'observed': observed,
              'status': 'handoff-incomplete' if failures else 'visible-handoff', 'failures': failures,
              'confirmedAt': confirmed, 'visibleHandoffAt': None if failures else confirmed}
    write_new(record, result)
    return result


def verify_confirmation(path: Path) -> dict:
    """Re-run, read only, every check ``confirm`` performed on an existing confirmation; raise on any failure.

    Stable shape (the batch authority's ``handoff`` command and its TEST stand-in rely on it): raises
    ``native_handoff_verify.ConfirmationRefused`` (a ``ValueError`` whose ``code`` names the failed check), or
    returns {'record': {path, sha256}, 'handoff': {path, sha256}, 'level': 'visible-handoff', 'mp4': {path, sha256},
    'viewsVerifiedAt', 'visibleHandoffAt' (wall clock), 'delivery': {path, sha256, status}}. Writes nothing.
    """
    from studio.native_handoff_verify import verify
    return verify(Path(path))
