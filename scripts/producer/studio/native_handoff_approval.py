"""Which batch approval a delivered export answers (requirement revision ``approved-content-production-2026-09-27``).

The batch authority bound at batch start is the single source of each clip's approved title and script, read
through A12's ``studio.production.api`` on the per-user authority root (canonical form approval-v2); no
caller-supplied approval is accepted and there is no stand-in (unit tests patch ``authority`` with a TEST reader).

An export whose request names a batch clip (``productionBudget``) is read by that name (``read_approval``): a
hand-off never falls back to "no batch binds this folder" for an export a batch charged. The project folder's own
binding (``approval_for_project``) must exist and name the same batch clip; a missing, unreadable or different
binding is reported as a binding problem (the record's APPROVAL_BINDING_MISSING), never guessed around. An export
that names no batch clip is read by its folder, and a folder no batch binds records ``not-supplied``: approval is
unknown there, never "not approved".
"""
from __future__ import annotations

from pathlib import Path

from studio import native_budget_store
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api as authority

REVISION = 'approved-content-production-2026-09-27'
FORM = 'approval-v2:'
READER = 'studio.production.api'  # the module `authority` names; recorded as readFrom
NOT_SUPPLIED = 'No batch authority binds this project; approval is unknown here, not refused.'


def supplied(found: dict, via: str) -> dict:
    """The authority's current approval row as the record carries it."""
    if not str(found.get('canonicalForm', '')).startswith(FORM):
        raise ValueError(f'Approved content: the authority approval is not {FORM[:-1]}')
    return {'status': 'supplied', 'readFrom': f'{READER}.{via}', 'requirementRevision': REVISION,
            'batchId': found['batchId'], 'clipId': found['clipId'], 'authorityStatus': found.get('status'),
            'historyCount': len(found.get('history') or []), 'approval': found['current']}


def not_supplied(found: dict | None) -> dict:
    """No current approval applies here (unknown, never refused)."""
    return {'status': 'not-supplied', 'meaning': NOT_SUPPLIED,
            **({'batchId': found['batchId'], 'clipId': found['clipId']} if found else {})}


def by_folder(project: Path) -> dict | None:
    """The approval of the clip whose batch binds this exact project folder, if any."""
    return authority.approval_for_project(native_budget_store.default_root(), project)


def binding_problem(named: tuple[str, str], folder: dict | None) -> str | None:
    """Why the folder's own binding does not confirm the batch clip the export names, or None."""
    bound = None if folder is None else (folder['batchId'], folder['clipId'])
    if bound == named:
        return None
    where = 'no batch binds this project folder' if bound is None else f'the folder is bound to batch {bound[0]} clip {bound[1]}'
    return f'the export names batch {named[0]} clip {named[1]}, but {where}'


def authority_approval(project: Path, production: dict | None) -> tuple[dict, str | None]:
    """The approval this delivery answers and any binding problem (the export's own name wins over the folder)."""
    folder = by_folder(project)
    named = ((production or {}).get('batchId'), (production or {}).get('clipId'))
    if not all(isinstance(value, str) and value for value in named):
        return (supplied(folder, 'approval_for_project') if folder and folder.get('current') else not_supplied(folder)), None
    try:
        found = authority.read_approval(native_budget_store.default_root(), *named)
    except (BudgetAuthorityError, ValueError) as error:
        return not_supplied(None), f'the export names batch {named[0]} clip {named[1]}, whose approval cannot be read: {error}'
    given = supplied(found, 'read_approval') if found.get('current') else not_supplied(found)
    return given, binding_problem(named, folder)
