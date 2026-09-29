"""Read-only re-verification of an existing visible hand-off confirmation (the batch authority's hand-off seam).

``native_handoff_confirm.verify_confirmation(path)`` calls ``verify``. It re-runs every check ``confirm``
performed, on the confirmation file as it is now, and raises ``ConfirmationRefused`` naming the first check
that fails (``code``). Checks, in order:

1. ``CONFIRMATION_NOT_VISIBLE``: a schema-1 confirmation whose status is ``visible-handoff`` with no failures and
   ``visibleHandoffAt`` equal to ``confirmedAt``.
2. ``HANDOFF_RECORD_CHANGED``: the hand-off record it binds re-hashes to its binding, is ``views-ready`` with no
   failures, names the same owner and view token, and was verified no later than the confirmation.
3. ``ATTESTATION_INVALID``: the recorded attestation is exactly what ``confirm`` admits for its pages.
4. ``MP4_CHANGED`` / ``DELIVERY_MISMATCH``: the served MP4 re-hashes to the bound SHA-256, and the attempt's
   ``delivery.json`` still names that path and SHA-256.
5. ``APPROVAL_BINDING_MISSING`` / ``APPROVED_CONTENT_DIFFERS_FROM_BUILD`` / ``APPROVAL_CHANGED_SINCE_HANDOFF``: the
   approved-content section recomputed now (the export's own ``productionBudget`` batch clip, the folder binding,
   and the title, word, cut-second, transcript and timing comparisons) has no binding problem and no mismatch, and
   answers the same approval and production as the record.
6. Every live condition ``confirm`` re-checks (``native_handoff_confirm.recheck``), under the codes it uses: the same
   registered Studio process, live, bound to the MP4 and serving the project; the project identity after that
   load; the same review-player server and row with the after-load label; and the served page's own ``playing``
   report of this exact MP4 route from a page load after ``viewsVerifiedAt``.
7. ``RECORDED_PLAYBACK_NOT_OBSERVED``: every playback report the confirmation records is one the live review
   player observed (a hand-written record's reports are not).

It writes nothing: no record, and the Studio registry entry is read under the registry's lock without the
refresh ``confirm`` performs. It returns {'record', 'handoff', 'level': 'visible-handoff', 'mp4', 'viewsVerifiedAt',
'visibleHandoffAt' (wall clock), 'delivery'}. What it cannot prove is what ``confirm`` cannot: that a person
watched or listened, that the window was visible, or that playback continued.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cut_preview_io import bound_json
from studio import managed_preview as managed
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio import native_handoff_confirm as confirmation
from studio import native_handoff_content as content
from studio import native_handoff_evidence as evidence
from studio.native_handoff_open import PRODUCTION_KEYS
from studio.native_runtime import digest

CONFIRMATION = 'native-visible-handoff-confirmation'
LEVEL = 'visible-handoff'


class ConfirmationRefused(ValueError):
    """An existing confirmation does not hold now; ``code`` names the failed check."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code with the reason."""
        super().__init__(f'{code}: {message}')
        self.code = code


def require(held: bool, code: str, message: str) -> None:
    """Refuse the confirmation by name unless ``held``."""
    if not held:
        raise ConfirmationRefused(code, message)


def view_status(project: str) -> dict:
    """The managed Studio view's state and liveness, read under the registry lock without refreshing or writing."""
    with registry.transaction(registry.monotonic_until(managed.DEFAULT_WAIT_SECONDS)) as reg:
        entry = registry.read_entry(reg, str(Path(project).resolve()))
    live = bool(entry and entry['state'] == 'running' and state.matches(entry))
    return {'preview': entry, 'live': live, 'media': registry.media_status(entry.get('media') if entry else None)}


def _confirmation(path: Path) -> tuple[dict, dict]:
    """The confirmation, its binding, and check 1."""
    file = path.resolve(strict=True)
    value, binding = bound_json(file), {'path': str(file), 'sha256': digest(file)}
    require(value.get('schemaVersion') == 1 and value.get('kind') == CONFIRMATION, 'CONFIRMATION_NOT_VISIBLE',
            f'{file} is not a native visible hand-off confirmation')
    visible = value.get('visibleHandoffAt')
    require(value.get('status') == LEVEL and value.get('failures') == [] and isinstance(visible, str)
            and visible == value.get('confirmedAt'), 'CONFIRMATION_NOT_VISIBLE',
            f"the confirmation is {value.get('status')!r} with failures {value.get('failures')!r}")
    return value, binding


def _handoff(value: dict) -> tuple[dict, dict]:
    """Check 2: the bound, unchanged views-ready record of the same view, verified before the confirmation."""
    bound = value.get('handoff') if isinstance(value.get('handoff'), dict) else {}
    try:
        record, binding = confirmation.read_handoff(Path(str(bound.get('path'))))
    except (OSError, ValueError) as error:
        raise ConfirmationRefused('HANDOFF_RECORD_CHANGED', f'the bound hand-off record is unreadable: {error}') from error
    require(binding == bound, 'HANDOFF_RECORD_CHANGED', f"{binding['path']} changed after its confirmation")
    verified = (record.get('timestamps') or {}).get('viewsVerifiedAt')
    require(record.get('kind') == 'native-visible-handoff' and record.get('status') == 'views-ready'
            and record.get('failures') == [] and isinstance(verified, str), 'HANDOFF_RECORD_CHANGED',
            'the bound record is not a views-ready hand-off with no failures')
    require((record.get('owner'), record.get('viewToken')) == (value.get('owner'), value.get('viewToken'))
            and datetime.fromisoformat(verified) <= datetime.fromisoformat(value['visibleHandoffAt']),
            'HANDOFF_RECORD_CHANGED', 'the confirmation names another view, or confirms before the views were verified')
    return record, binding


def _attestation(value: dict, record: dict) -> None:
    """Check 3: the recorded attestation is exactly what confirm admits for its pages."""
    stated = value.get('attestation') if isinstance(value.get('attestation'), dict) else {}
    pages = tuple(stated.get(key) for key in ('reviewPage', 'studioPage', 'browser', 'attestedBy'))
    try:
        expected = confirmation.attestation_for(record, pages)
    except ValueError as error:
        raise ConfirmationRefused('ATTESTATION_INVALID', str(error)) from error
    require(stated == expected, 'ATTESTATION_INVALID', 'the recorded attestation is not the one confirm writes')


def _delivery(record: dict) -> dict:
    """Check 4: the MP4 still has the bound bytes and the attempt's delivery receipt still names them."""
    mp4, attempt = record['output']['mp4'], Path(record['attempt'])
    require(Path(mp4['path']).is_file() and digest(Path(mp4['path'])) == mp4['sha256'], 'MP4_CHANGED',
            f"{mp4['path']} no longer has the bytes the hand-off bound")
    file = attempt / 'delivery.json'
    delivery = bound_json(file)
    require((delivery.get('output'), delivery.get('sha256')) == (mp4['path'], mp4['sha256']), 'DELIVERY_MISMATCH',
            f'{file} no longer names the delivered MP4 and its SHA-256')
    return {'path': str(file), 'sha256': digest(file), 'status': delivery.get('status')}


def _approved_content(record: dict) -> None:
    """Check 5: the approved-content section recomputed now holds and answers the record's approval."""
    production = bound_json(Path(record['attempt']) / 'export-request.json').get('productionBudget')
    now = content.section(Path(record['project']['path']),
                          production and {key: production.get(key) for key in PRODUCTION_KEYS})
    problem = now['approvalBinding']['problem']
    require(problem is None, 'APPROVAL_BINDING_MISSING', str(problem))
    failed = content.mismatches(now)
    require(not failed, 'APPROVED_CONTENT_DIFFERS_FROM_BUILD', ', '.join(failed) + ' is false now')
    before, after = record['content']['operatorApproval'], now['operatorApproval']
    same = (before.get('status'), (before.get('approval') or {}).get('identity'), record['content'].get('production')) \
        == (after.get('status'), (after.get('approval') or {}).get('identity'), now['production'])
    require(same, 'APPROVAL_CHANGED_SINCE_HANDOFF', 'the approval or production this delivery answers changed')


def _live(value: dict, record: dict) -> None:
    """Checks 6 and 7: confirm's live re-check, and the recorded playback among what the player observed."""
    failures, observed = confirmation.recheck(record, view_status)
    if failures:
        raise ConfirmationRefused(failures[0]['code'], failures[0]['message'])
    recorded = (value.get('observed') or {}).get('reviewPagePlayback')
    live = observed['reviewPagePlayback']
    require(isinstance(recorded, list) and bool(recorded) and all(row in live for row in recorded),
            'RECORDED_PLAYBACK_NOT_OBSERVED', 'the playback the confirmation records is not what the review player '
            'observed from the served page')


def verify(path: Path) -> dict:
    """Every check, in order; the summary the batch authority records."""
    value, binding = _confirmation(path)
    record, handoff_binding = _handoff(value)
    _attestation(value, record)
    delivery = _delivery(record)
    _approved_content(record)
    _live(value, record)
    mp4 = record['output']['mp4']
    return {'record': binding, 'handoff': handoff_binding, 'level': LEVEL,
            'mp4': {'path': mp4['path'], 'sha256': mp4['sha256']},
            'viewsVerifiedAt': record['timestamps']['viewsVerifiedAt'], 'visibleHandoffAt': value['visibleHandoffAt'],
            'delivery': delivery}
