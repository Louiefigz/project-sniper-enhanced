"""Which batch and logical output own a native project, derived only from batch records.

There is no separate index: every decision scans the validated batch records,
so deleting or editing a lookup file cannot unbind anything. A bound folder is
identified by its directory's (device, inode), so case variants and symlinks
of one folder are the same project. Its format and content hash, and a Short's
selection (``native_budget_selection``) or a Long's manifest lineage
(``production.lineage``), identify copies and same-format revisions of it.

Resolution for an export launch:
- bound to a clip of the current batch → that clip's budget (a draining batch
  then refuses the launch: shutdown admits no new work);
- otherwise, while a batch is active or draining → refused until the coordinator
  binds it (a new folder, a copy or a changed HOME cannot opt out);
- otherwise, the same folder, content or Short as a clip of a closed batch →
  refused: that budget is spent; new work needs a new batch that binds it, or
  the operator's explicit ``archive`` of the closed batch;
- otherwise → unbudgeted, exactly as before.
Supporting owners use ``owner_binding`` (native_budget_owner): a folder bound to the
active batch gets a utility grant; one bound to a draining or closed live batch is
refused, so supporting compute cannot outlive its batch; unbound folders run as before.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from studio.native_budget_batches import BudgetRefused, current_batches, list_batches, live_records
from studio.native_budget_schema import SHA256
from studio.native_budget_selection import project_selection, shared_share
from studio.native_budget_store import BudgetAuthorityError
from studio.production.lineage import long_identity, output_match, project_format

__all__ = ['BudgetRefused', 'project_identity', 'project_output_seconds', 'resolve_binding', 'active_binding',
           'owner_binding', 'binding_refusal', 'PROJECT_ROW']
PROJECT_ROW = ('key', 'path', 'projectHash', 'selection')


def project_identity(project: Path) -> dict:
    """Folder identity (device, inode), format, content hash, and a Short's selection or a Long's lineage.

    A stored project row keeps ``PROJECT_ROW`` (a Long's selection is None: its lineage is bound once on its
    output row).
    """
    try:
        info, fmt = project.stat(), project_format(project)
        fields = _short_fields(project) if fmt == 'short' else _long_fields(project)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise BudgetRefused(f'Cannot identify {project} for the production budget: {error}') from error
    key = hashlib.sha256(f'{info.st_dev}:{info.st_ino}'.encode()).hexdigest()
    return {'key': key, 'path': str(project), 'format': fmt, **fields}


def _short_fields(project: Path) -> dict:
    """A Short's built manifest content hash (None before building) and its selection."""
    manifest = project / 'PROJECT-MANIFEST.json'
    content = json.loads(manifest.read_text())['projectHash'] if manifest.is_file() else None
    if content is not None and (type(content) is not str or SHA256.fullmatch(content) is None):
        raise ValueError(f'{manifest} has no valid projectHash')
    return {'projectHash': content, 'selection': project_selection(project), 'lineage': None}


def _long_fields(project: Path) -> dict:
    """A Long's content hash (its LONG-PROJECT.json bytes) and lineage (request and recordings)."""
    return {**long_identity(project), 'selection': None}


def project_output_seconds(project: Path) -> float:
    """Authored program duration from the project's explicit frame clock (either format's plan)."""
    plan = 'LONG-PROJECT.json' if project_format(project) == 'long' else 'SHORT-PROJECT.json'
    canvas = json.loads((project / plan).read_text())['canvas']
    numerator, denominator = map(int, canvas['frameRate'].split('/'))
    return canvas['totalFrames'] * denominator / numerator


def clip_owning(record: dict, identity: dict) -> str | None:
    """The clip of this record that owns the project folder, if any."""
    for clip_id, clip in record['clips'].items():
        if any(row['key'] == identity['key'] for row in clip['projects']):
            return clip_id
    return None


def _matching_clip(record: dict, identity: dict) -> str | None:
    """The clip holding this folder, identical content, or the same output (same-format revision)."""
    return next((clip_id for clip_id, clip in record['clips'].items() if output_match(clip, identity)), None)


def _the_current_batch(root: Path) -> tuple[str, dict] | None:
    """The one active or draining batch, if any; two at once is corrupt authority."""
    current = current_batches(root)
    if len(current) > 1:
        raise BudgetAuthorityError(f'Batches {[name for name, _ in current]} are all active or draining; '
                                   'only one may be')
    return current[0] if current else None


def resolve_binding(root: Path, project: Path) -> dict | None:
    """Return {'batchId','clipId'}, None when unbudgeted, or raise BudgetRefused."""
    if not list_batches(root):
        return None
    identity = project_identity(project)
    current = _the_current_batch(root)
    if current is not None:
        batch_id, record = current
        clip_id = clip_owning(record, identity)
        if clip_id is None and record['status'] == 'draining':
            raise BudgetRefused(f'Production batch {batch_id} is draining: no new work runs until its '
                                'unresolved work settles and it closes')
        if clip_id is None:
            raise BudgetRefused(f'Production batch {batch_id} is active: bind this project to one of its clips '
                                f'(native_batch.py bind --batch {batch_id} --clip <clip-id> {project}) '
                                'before exporting it')
        return {'batchId': batch_id, 'clipId': clip_id}
    for batch_id, record in reversed(live_records(root)):
        clip_id = _matching_clip(record, identity)
        if clip_id is not None:
            raise BudgetRefused(f'This project is clip {clip_id} of closed batch {batch_id}, whose budget is '
                                'spent. New work needs the operator\'s explicit new request: a new batch '
                                'that binds it, or archiving that batch')
    return None


def active_binding(root: Path, project: Path) -> dict | None:
    """The active batch's clip that owns this folder, or None; never a refusal."""
    binding = owner_binding(root, project)
    return {'batchId': binding['batchId'], 'clipId': binding['clipId']} \
        if binding and binding['status'] == 'active' else None


def owner_binding(root: Path, project: Path) -> dict | None:
    """{'batchId','clipId','status','format'} of the live batch owning this exact folder, or None.

    ``format`` is the plan the folder declares now ('short' or 'long'); a supporting grant is refused when it is
    not its output's format (``native_budget_binding.reserve_utility``).

    The current (active or draining) batch wins; otherwise the latest closed live batch
    that bound the folder. Archiving is the explicit release.
    """
    if not list_batches(root):
        return None
    identity = project_identity(project)
    current = _the_current_batch(root)
    candidates = [current] if current else []
    candidates += [row for row in reversed(live_records(root)) if row[1]['status'] == 'closed']
    for batch_id, record in candidates:
        clip_id = clip_owning(record, identity)
        if clip_id:
            return {'batchId': batch_id, 'clipId': clip_id, 'status': record['status'], 'format': identity['format']}
    return None


def binding_refusal(record: dict, clip_id: str, identity: dict) -> str | None:
    """A folder, its exact content, or the same output can belong to only one clip of a batch.

    A Short cut from a Long's recording is not that Long (formats differ): it is refused only as a copy.
    """
    for other_id, other in record['clips'].items():
        match = None if other_id == clip_id else output_match(other, identity)
        if match == 'project':
            return f'This project (or identical content) already belongs to clip {other_id}'
        if match == 'revision':
            return _revision_refusal(other_id, other, identity)
    return None


def _revision_refusal(other_id: str, other: dict, identity: dict) -> str:
    """Why a same-format revision of another output cannot open fresh counters."""
    if identity['format'] == 'long':
        return (f'This Long project shares Long {other_id}\'s lineage (its request or most of its recordings): '
                'a revision stays with its Long and its counters')
    share = max(shared_share(row['selection'], identity['selection']) for row in other['projects'])
    return (f'This project re-cuts clip {other_id}\'s selection ({share:.0%} of its source seconds): '
            'a revision stays with its clip and its counters')
