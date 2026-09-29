"""Admit sealed retained picture work for the next revision of the same Short.

Discovery grants nothing. A donor must pass the checked-delivery reader or the
explicit unfinished-render reader, plus its complete batched-picture inventory,
before its frame paths enter an immutable request. The worker revalidates locality and every pin before
copy/capture. Existing streaming outputs remain readable but are not patch donors.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_clip_lineage import lineage_projects
from studio.native_export_history import candidate_attempts, lineage_attempts
from studio.native_runtime import digest
from studio.native_short_revision_baseline import baseline_pins, frame_root, read_baseline
from studio.native_short_picture_reuse import MAX_RECEIPT_BYTES
from studio.native_short_revision_proof import MODE, POLICY, revision_intervals
from studio.native_stage_evidence import require, verify_pins

FINAL = 'native-short-checked-for-review'
TERMINAL = {FINAL, 'failed', 'native-short-rendered-awaiting-qc'}


def repair_candidates(request: dict) -> list[tuple[str, Path]]:
    """Select only completed checked media of this project or its verified ancestors."""
    allowed = set(lineage_projects(Path(request['project'])))
    found = []
    for attempt in sorted(set(candidate_attempts(request)) | set(lineage_attempts(request))):
        row = repair_candidate(attempt, allowed)
        if row:
            found.append(row)
    return sorted(found, reverse=True)


def repair_candidate(attempt: Path, allowed: set[str]) -> tuple[str, Path] | None:
    """Cheap shape filter; cryptographic and ownership admission happens before reuse."""
    request_file, delivery_file = attempt / 'export-request.json', attempt / 'delivery.json'
    if not request_file.is_file() or not delivery_file.is_file():
        return None
    previous, delivery = bound_json(request_file), bound_json(delivery_file)
    if previous.get('project') not in allowed or delivery.get('status') not in TERMINAL:
        return None
    if delivery.get('status') != FINAL and not (attempt / 'render-stage.json').is_file():
        return None
    completed = delivery.get('completedAt')
    require(isinstance(completed, str) and bool(completed), 'Checked picture donor has no completion time')
    return completed, attempt


def admitted_revision(request: dict, attempt: Path) -> tuple[dict | None, dict, str]:
    """Bind the complete baseline QC and exact retained frame inventory to local repair."""
    previous = bound_json(attempt / 'export-request.json')
    plan, reason = revision_intervals(request, previous)
    if plan is None:
        return None, {}, reason
    receipt_file = frame_root(previous, attempt) / 'batched-picture.json'
    if not receipt_file.is_file():
        return None, {}, 'Checked output has no retained batched picture inventory; establish a new baseline'
    checked, pins, qualification = read_baseline(attempt)
    require(checked == previous, 'Picture donor request changed during checked-delivery admission')
    frame_attempt, frame_request, frame_pins = baseline_pins(checked, attempt)
    pins.update(frame_pins)
    receipt = bound_json(receipt_file, pins[str(receipt_file)], maximum=MAX_RECEIPT_BYTES)
    frames = [{key: row[key] for key in ('frame', 'path', 'sha256')} for row in receipt['frames']]
    require([row['frame'] for row in frames] == list(range(plan['totalFrames'])), 'Repair donor omits picture frames')
    value = {'schemaVersion': 1, 'policy': POLICY, **plan, 'donorFrames': frames,
             'donor': {'attempt': str(frame_attempt), 'project': frame_request['project'],
                       'requestSha256': digest(frame_attempt / 'export-request.json'),
                       'pictureReceiptSha256': digest(receipt_file), 'checkedAttempt': str(attempt),
                       'checkedDeliverySha256': digest(attempt / 'delivery.json'), 'qualification': qualification}}
    return value, pins, reason


def bind_picture_revision(request: dict) -> dict:
    """Choose the latest compatible checked baseline; preserve explicit reuse/recovery routes."""
    skipped = ('verifyStage', 'pictureDonor', 'promoteDraft', 'reviewDraft', 'previewOnly')
    if request.get('adapter') == 'native-long' or any(request.get(key) for key in skipped):
        return request
    reason = 'No checked same-clip baseline with retained picture frames is available'
    for _completed, attempt in repair_candidates(request):
        revision, pins, reason = admitted_revision(request, attempt)
        if revision is None:
            continue
        require(all(request['pins'].get(name, sha) == sha for name, sha in pins.items()),
                'Picture repair donor conflicts with current immutable inputs')
        request['pins'].update(pins)
        request['pictureRevision'] = revision
        request['pictureRevisionDisposition'] = {'mode': 'scoped-repair', 'reason': reason}
        return request
    request['pictureRevisionDisposition'] = {'mode': 'full-rebuild', 'reason': reason}
    return request


def verify_picture_revision(request: dict) -> dict | None:
    """Re-prove donor QC, exact intervals and every bound byte immediately before rendering."""
    revision = request.get('pictureRevision')
    if revision is None:
        return None
    require(request.get('captureMode') == MODE, 'Picture repair requires the retained-frame route')
    attempt = Path(revision['donor']['checkedAttempt'])
    output = Path(request['output'])
    require(output != attempt and not output.is_relative_to(attempt) and not attempt.is_relative_to(output),
            'Picture repair must preserve the original checked attempt')
    expected, pins, _reason = admitted_revision(request, attempt)
    require(expected == revision, 'Picture repair inputs or derived dirty ranges changed')
    require(all(request['pins'].get(name) == sha for name, sha in pins.items()),
            'Picture repair donor proof was not pinned before launch')
    verify_pins(pins)
    return revision
