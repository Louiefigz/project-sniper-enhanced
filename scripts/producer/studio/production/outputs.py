"""Outputs joining an active run: the immutable authorization event that starts an output's own clock.

A new output joins an active run only through ``authorize_output``. The event records its format, the
elapsed run time it was authorized at (its own clock start under the run anchor, never reset), its
deadlines and policy (``production.formats``), who or what recorded it, and for a Short its approved
title and script (bound as it is authorized) and the Long it was derived from, if any. It is admitted
only if the mixed forecast still fits every committed output (``production.mixed_forecast``); a refusal
names the conflict and commits nothing.

- A Long may join at any time while the run is active, after the Shorts' minute 25 included.
- A genuinely new approved Short joins any active run on its own 40 counted minutes from its own
  authorization (C8): through ``add-clip`` (``approvals.add_clip``, which authorizes it here) or as a Long's
  derivation (its approved script must cut one of the Long's bound recordings). No minute 25 of the batch
  clock applies; the forecast admits or refuses it by name.
- The same job never gets a new clock (C-2, X144, X159): ``same_job`` refuses a Short that is the same job as another
  clip's current approval or one in its recorded revision lineage: the same folded title, source and ordered kept
  words (``duplication_check.one_job``; range grouping, derived seconds and transcript bytes are not the job).
  Overlapping source seconds alone never refuse; ``duplication_check`` records them on the adding event. A rename
  goes through ``change-approval``, which keeps the lineage and the clock.

Binding checks the format (a Short project for a Short output, a Long project for a Long output), binds a
Long's lineage once from its first project, and keeps a derived Short on its Long's recordings.
``freeze_expired`` stops a Short's work once its own deadline passes in every active run, so neither a Long nor
a later Short keeps an expired Short's AI work alive; it never stops a Long.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from studio.native_budget_policy import Approval, approval_row, clip_record, new_clip
from studio.native_budget_registry import BudgetRefused, owner_binding
from studio.native_budget_schema import BOUNDS, valid_title
from studio.native_budget_store import read_any_batch, require_clip_id
from studio.production.duplication_check import duplication_check, one_job
from studio.production.formats import (
    FORMATS, LONG_POLICY, clip_deadlines, expected_deadlines, output_format, output_identity,
)
from studio.production.lifecycle import freeze
from studio.production.lineage import same_long
from studio.production.mixed_forecast import admission_refusal
from studio.production.tasks import TaskConflict, TaskRefused


@dataclass(frozen=True)
class OutputAuthorization:
    """One output the operator authorizes into the running batch.

    ``approval`` is required for a Short (its approved title and script); ``output_seconds`` for a Long
    (its declared duration, at most 900 seconds); ``derived_from`` names the Long a Short derives from.
    """

    clip_id: str
    format: str
    reason: str
    recorded_by: str
    approval: Approval | None = None
    output_seconds: float | None = None
    derived_from: str | None = None


def _request_refusal(record: dict, request: OutputAuthorization) -> str | None:
    """Run state, bounds and the recorded reason and recorder."""
    if record['status'] != 'active':
        return f'Batch {record["batchId"]} is {record["status"]}; no output can join it'
    if len(record['clips']) >= BOUNDS['clips']:
        return 'The batch already has the maximum number of outputs'
    recorder = request.recorded_by
    if type(request.reason) is not str or not request.reason.strip() or not valid_title(recorder) \
            or len(recorder) > 128 or '\n' in recorder:
        return 'An authorization records its reason and who or what recorded it (one line, at most 128 characters)'
    return None


def _shape_refusal(request: OutputAuthorization) -> str | None:
    """A Long declares its duration and nothing else; a Short brings its approval and no duration."""
    seconds = request.output_seconds
    if request.format == 'short':
        return 'A Short joins with its approved title and script (its duration comes from them)' \
            if request.approval is None or seconds is not None else None
    if request.approval is not None or request.derived_from is not None:
        return 'A Long has no Short approval and derives from nothing'
    if type(seconds) not in (int, float) or not 0 < seconds <= LONG_POLICY['maxOutputSeconds']:
        return f'A Long declares its output duration in seconds (at most {LONG_POLICY["maxOutputSeconds"]})'
    return None


def _short_refusal(record: dict, request: OutputAuthorization) -> str | None:
    """A Short on its own clock joins any active run (C8); a derived one names a Long it verifiably cuts."""
    source = request.derived_from
    if source is None:
        return None
    long = record['clips'].get(source)
    if long is None or output_format(long) != 'long':
        return f'A derived Short names a Long output of this run ({source} is not one)'
    lineage = long['output']['lineage']
    if lineage is None:
        return f'Long {source} has no bound project yet; bind it before authorizing a Short derived from it'
    if request.approval.source_sha256 not in lineage['sources']:
        return f'The approved script cuts a recording that Long {source} was not prepared from'
    return None


def _new_output(record: dict, request: OutputAuthorization, elapsed: float) -> dict:
    """The clip with its approval (a Short) and its immutable output row."""
    long = request.format == 'long'
    approvals = [] if long else [approval_row(request.approval, elapsed, record['clock']['epoch'],
                                              'approved title and script bound when the output was authorized; '
                                              'its own clock starts here')]
    clip = new_clip(request.reason[:512], True, approvals)
    seconds = float(request.output_seconds) if long else None
    preparation, delivery = expected_deadlines(request.format, elapsed, seconds)
    row = {'format': request.format, 'authorizedElapsed': elapsed, 'deadlineElapsed': delivery,
           'preparationElapsed': preparation, 'outputSeconds': seconds, 'derivedFrom': request.derived_from,
           'lineage': None, 'recordedBy': request.recorded_by,
           'policy': json.loads(json.dumps(LONG_POLICY)) if long else None, 'identity': ''}
    row['identity'] = output_identity(record['batchId'], request.clip_id, row, clip)
    clip['output'] = row
    if long:
        clip.pop('capacityClock', None)
    return clip


def authorize_output(record: dict, request: OutputAuthorization, elapsed: float) -> dict:
    """Add one output with its own clock to the caller's locked record; raises on any refusal.

    An identical repeated authorization (a lost acknowledgement) returns ``replayed`` and changes nothing; it
    carries no ``duplicationCheck`` (the caller reads the recorded one from the adding event, X144). A new Short that
    is the same job as another clip is refused by name (``same_job``) before the forecast runs; a distinct one carries
    its ``duplicationCheck`` (None when nothing overlaps) for the caller's event.
    """
    clip_id = require_clip_id(request.clip_id)
    if request.format not in FORMATS:
        raise ValueError(f'An output is one of {", ".join(FORMATS)}')
    existing = record['clips'].get(clip_id)
    if existing is not None:
        row, shaped = existing.get('output'), _shape_refusal(request) is None
        if row is None or not shaped or row['identity'] != _new_output(record, request, elapsed)['output']['identity']:
            raise TaskConflict(f'Output {clip_id} already exists with a different authorization')
        return {'clipId': clip_id, 'output': row, 'replayed': True}
    refusal = _request_refusal(record, request) or _shape_refusal(request)
    if refusal is None and request.format == 'short':
        refusal = _short_refusal(record, request)
    if refusal:
        raise TaskRefused(refusal)
    candidate = _new_output(record, request, elapsed)
    refusal = same_job(record, clip_id, candidate)
    if refusal:
        raise TaskRefused(refusal)
    check = duplication_check(record, clip_id, candidate)
    record['clips'][clip_id] = candidate
    refusal = admission_refusal(record, clip_id, elapsed)
    if refusal:
        del record['clips'][clip_id]
        raise TaskRefused(refusal)
    return {'clipId': clip_id, 'output': candidate['output'], 'replayed': False, 'duplicationCheck': check}


def same_job(record: dict, clip_id: str, candidate: dict) -> str | None:
    """The refusal of an effective duplicate of another clip of the run, or None (C-2; P4-10 reuses it).

    ``candidate`` is the clip being authorized; its first approval is what it binds. It is the same job as another
    clip when that approval is ``one_job`` with the other clip's current approval or one of its earlier approvals,
    its recorded revision lineage (``change-approval``): the same folded title, source and ordered kept words,
    however its ranges and seconds are cut (X144, X159). A retry, re-add or rename of the same job never gets a new
    clock. Overlapping source seconds alone never refuse: ``duplication_check`` records them.
    """
    first = candidate['approvals'][0] if candidate['approvals'] else None
    others = [other for other, clip in sorted(record['clips'].items())
              if first is not None and other != clip_id and any(one_job(first, row) for row in clip['approvals'])]
    if not others:
        return None
    return (f'Clip {others[0]} already carries this approved script: a retry, re-add or rename of the same job never '
            f'gets a new clock; change it with change-approval --clip {others[0]}')


def freeze_expired(record: dict, elapsed: float) -> list[str]:
    """In every active run, stop a Short's work once its own deadline passes (C8).

    Each Short keeps its own deadline (``clip_deadlines``), so a later Short or a Long keeps the run open while
    an expired Short's unlaunched tasks are cancelled and its live ones asked to stop (slots stay held until
    confirmed), as ``close`` does at minute 40. A Long is never stopped by this: its live work settles at close.
    """
    if record['status'] != 'active':
        return []
    frozen = []
    for clip_id, clip in record['clips'].items():
        expired = elapsed >= clip_deadlines(record, clip)['deliverySeconds']
        if expired and clip['state'] != 'handed-off' and output_format(clip) == 'short':
            frozen += freeze(record, clip_id, f'Short {clip_id} reached its own delivery deadline', elapsed)
    return frozen


def format_refusal(record: dict, clip_id: str, identity: dict) -> str | None:
    """A Short project binds only to a Short output and a Long project only to a Long output."""
    fmt, project = output_format(record['clips'][clip_id]), identity['format']
    return None if project == fmt else f'Output {clip_id} is a {fmt}; this project is a {project} project'


def binding_refusal(record: dict, clip_id: str, identity: dict) -> str | None:
    """A Long stays on its lineage and within its authorized duration; a derived Short on its Long's recordings."""
    clip = record['clips'][clip_id]
    fmt, row = output_format(clip), clip.get('output')
    if fmt == 'long':
        lineage, seconds = row['lineage'], identity['outputSeconds']
        if lineage is not None and not same_long(lineage, identity['lineage']):
            return (f'This Long project was prepared from another request and other recordings than Long {clip_id}; '
                    'a different Long needs its own authorization')
        if seconds is not None and seconds > row['outputSeconds'] + 1e-6:
            return (f'Long {clip_id} was authorized for {row["outputSeconds"]:.0f} s and this project runs '
                    f'{seconds:.1f} s; a longer cut needs its own authorization')
        return None
    source = row['derivedFrom'] if row else None
    if source and identity['selection']['source'] not in record['clips'][source]['output']['lineage']['sources']:
        return f'Short {clip_id} derives from Long {source}; its project must cut one of that Long\'s recordings'
    return None


def read_output(root: Path, batch_id: str, clip_id: str) -> dict:
    """An output's format identity (live or archived batch), read without any Short approval.

    The Long owner and critics (units D2/D3) name the batch and clip a Long project belongs to from
    this, and read its format, own clock, latest final-render admission, deadline and lineage.
    """
    record = read_any_batch(root, batch_id)
    clip = clip_record(record, clip_id)
    row, deadlines = clip.get('output'), clip_deadlines(record, clip)
    return {'batchId': batch_id, 'clipId': clip_id, 'status': record['status'], 'format': output_format(clip),
            'clock': 'own' if row else 'batch', 'authorizedElapsed': row['authorizedElapsed'] if row else None,
            'preparationElapsed': deadlines['preparationSeconds'], 'deadlineElapsed': deadlines['deliverySeconds'],
            'outputSeconds': row['outputSeconds'] if row else None, 'lineage': row['lineage'] if row else None,
            'derivedFrom': row['derivedFrom'] if row else None, 'identity': row['identity'] if row else None,
            'projects': [project['path'] for project in clip['projects']]}


def long_launch_binding(root: Path, found: dict, identity: dict) -> dict:
    """What a Long launch binds, read from its output row: raises BudgetRefused when the project left that Long.

    ``found`` is the launch's resolved batch and clip; ``identity`` the project's (``registry.project_identity``).
    The project must still be that Long output's project: the same format, its lineage (the same request, or mostly
    the same recordings) and a finished canvas no longer than the authorized duration, all rechecked here because
    a bound folder can be edited after binding.
    """
    record = read_any_batch(root, found['batchId'])
    clip = clip_record(record, found['clipId'])
    fmt, row = output_format(clip), clip.get('output')
    refusal = None if fmt == 'long' and identity['format'] == 'long' \
        else f'Output {found["clipId"]} is a {fmt}; the Long public entry exports a Long project of a Long output'
    if refusal is None and identity['outputSeconds'] is None:
        refusal = f'This Long project has no canvas yet; export its finished composition (output {found["clipId"]})'
    refusal = refusal or binding_refusal(record, found['clipId'], identity)
    if refusal:
        raise BudgetRefused(refusal)
    return {'format': 'long', 'project': identity['path'], 'planSha256': identity['projectHash'],
            'lineage': identity['lineage'], 'outputSeconds': identity['outputSeconds'],
            'authorizedSeconds': row['outputSeconds'], 'identity': row['identity']}


def output_for_project(root: Path, project: Path) -> dict | None:
    """``read_output`` for the output that owns this exact project folder (either format), or None."""
    binding = owner_binding(root, project)
    return read_output(root, binding['batchId'], binding['clipId']) if binding else None


def bind_lineage(clip: dict, identity: dict) -> bool:
    """A Long's first project binds its lineage (once; later projects must be the same Long)."""
    row = clip.get('output')
    if row is None or row['format'] != 'long' or row['lineage'] is not None:
        return False
    row['lineage'] = identity['lineage']
    return True
