"""Budget hooks used inside a running export: owner limits, nested charges, outcome.

Every owner of a budgeted request gets the smaller of its own stage limit and
the inherited deadline minus the cleanup reserve, queues (bounded by that same
allowance) instead of failing on a busy slot, and carries the granted
allocation so its monitor stops the child at the hard deadline even across
system sleep. Owners of a request admitted without a budget are marked as
serving no batch, so a batch that starts later never refuses or bounds them.

A supporting owner started outside an export (review bundle, audio stage,
cache alias, owned inspection) consults the authority for the native Short or
Long projects it serves (``NativeRunConfig.serves``, else its own project folder
when it declares a plan). A project bound to a clip of the active batch gets a
utility grant (a Long's ends by that Long's own deadlines), or a refusal once that clip
is handed off or the deadline passes. A project bound to a draining or closed
live batch is refused: supporting compute is not a way around the end of its
batch (a new batch that binds it, or archiving, is the release). Playback of a
delivered MP4 and its Studio view does not run through these owners. Unbound
projects run unchanged: the active-batch refusal of unbound work belongs to
export launches only.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from native_work_pool_policy import DISK_RESERVATION_BYTES
from studio.native_run_config import NativeRunConfig
from studio.native_stage_evidence import require
from studio.native_budget_binding import (
    BudgetRefused, charge_request, owner_binding, record_request_outcome, reserve_utility,
)
from studio.native_budget_clock import MIN_STAGE_SECONDS, allocation_remaining, stage_allowance
from studio.native_budget_store import BudgetAuthorityError, default_root
from studio.production.outputs import read_output

MAX_CAPACITY_WAIT = 600


def budget_owner_settings(request: dict, settings: object) -> object:
    """Bound one NativeRunConfig by the inherited deadline (raises when exhausted)."""
    budget = request.get('productionBudget')
    if not budget:
        return replace(settings, serves=())
    allowance = stage_allowance(request, settings.deadline)
    return replace(settings, deadline=allowance, capacity_wait_seconds=min(MAX_CAPACITY_WAIT, allowance),
                   hard_deadline=budget['allocation'])


def record_budget_outcome(request: dict, result: dict) -> str | None:
    """Close the reserved launch; authority failure never hides a completed MP4."""
    try:
        if request.get('productionBudget', {}).get('familyId'):
            from studio.native_budget_family import record_family_outcome
            record_family_outcome(request, result)
        elif request.get('productionBudget', {}).get('continuationOf'):
            from studio.native_budget_continuation import record_review_outcome
            record_review_outcome(request, result)
        else:
            record_request_outcome(request, result)
    except (BudgetAuthorityError, BudgetRefused, ValueError) as error:
        return f'{type(error).__name__}: {error}'
    return None


def served_projects(owner: object) -> tuple[Path, ...]:
    """The native project folders (a Short's or a Long's plan) whose budget applies to this owner."""
    serves = owner.settings.serves
    if serves is not None:
        return tuple(serves)
    plans = ('SHORT-PROJECT.json', 'LONG-PROJECT.json')
    return (owner.project,) if any((owner.project / plan).is_file() for plan in plans) else ()


def apply_budget_to_owner(owner: object) -> None:
    """A supporting owner of bound clips inherits the tightest granted deadline, or is refused.

    Each served bound clip is asked separately, Shorts first. When every served output shares one deadline (Shorts
    on the batch clock), the owner runs when at least one admits it (a multi-clip hand-off bundle is not blocked by
    one clip that missed its window) and is refused only when every served bound clip refuses. When the served
    outputs have different deadlines (a Long, or a Short on its own clock), any served Short's refusal refuses the
    owner before anything else is granted: a later deadline never keeps a Short's supporting work alive.
    """
    if owner.hard_deadline is not None:
        return
    root = default_root()
    served = [(binding, read_output(root, binding['batchId'], binding['clipId'])) for binding in
              filter(None, (owner_binding(root, project) for project in served_projects(owner)))]
    mixed = len({(output['batchId'], output['deadlineElapsed']) for _binding, output in served}) > 1
    grants, refusals = [], []
    for binding, output in sorted(served, key=lambda row: row[1]['format'] != 'short'):
        grant, refusal = _ask(root, binding, owner.label)
        if refusal is not None and mixed and output['format'] == 'short':
            raise BudgetRefused(f'{refusal} (Short {output["clipId"]}). This owner also serves outputs with later '
                                'deadlines; a later deadline never keeps a Short\'s supporting work alive') from refusal
        grants += [grant] if grant else []
        refusals += [refusal] if refusal else []
    if refusals and not grants:
        raise refusals[0]
    if grants:
        owner.production_allocations = tuple(grants)
        owner.hard_deadline = min(grants, key=lambda grant: grant['epochDeadline'])
        allocation = {'productionBudget': {'allocation': owner.hard_deadline}}
        owner.deadline = stage_allowance(allocation, owner.deadline)


def _ask(root: object, binding: dict, label: str) -> tuple[dict | None, BudgetRefused | None]:
    """(grant, None) or (None, refusal) for one served bound clip."""
    try:
        return _utility_grant(root, binding, label), None
    except BudgetRefused as refusal:
        return None, refusal


def _utility_grant(root: object, binding: dict, label: str) -> dict:
    """A grant from the active batch; a draining or closed batch refuses supporting compute."""
    if binding['status'] != 'active':
        raise BudgetRefused(f'Clip {binding["clipId"]} belongs to {binding["status"]} batch {binding["batchId"]}: '
                            'supporting compute for it needs a new batch that binds it, or the operator\'s '
                            'archive of that batch')
    return reserve_utility(root, binding, f'owner:{label}')['allocation']


def deadline_is_budget_limit(grant: dict | None) -> bool:
    """True when an owner stopped because the inherited allocation, not its own limit, ran out."""
    return bool(grant) and allocation_remaining(grant) <= grant['cleanupReserveSeconds'] + MIN_STAGE_SECONDS


def aac_budget_hook(request: dict, premaster_sha256: str, profile_identity: str) -> Callable[[int], None] | None:
    """Pre-charge each final-delivery AAC/master candidate against its exact audio input."""
    if not request.get('productionBudget'):
        return None
    audio_key = hashlib.sha256(f'{premaster_sha256}:{profile_identity}'.encode()).hexdigest()

    def charge_candidate(_index: int) -> None:
        """Charge one candidate before its master/AAC work starts."""
        charge_request(request, 'aacCandidate', audio_key)
    return charge_candidate


def long_owner_disk(settings: NativeRunConfig, request: dict, label: str) -> NativeRunConfig:
    """Reserve Long private output bytes; source-store acquisition expands shared allocation before writing."""
    from studio.native_segments.frame_metadata import require_retained_metadata_capacity
    require_retained_metadata_capacity(request, settings.additional_pins)
    if label not in ('capture', 'picture', 'pipeline') and not label.startswith('segment-picture-'):
        return replace(settings, disk_expansion=True)
    projection = request.get('diskProjection')
    require(isinstance(projection, dict) and all(type(projection.get(key)) is int and projection[key] >= 0
                                               for key in ('sampleBytes', 'outputBytes', 'miscBytes')),
            'Long request lacks disk projection; prepare with native_long_export.py')
    written = projection['sampleBytes'] if label == 'capture' else projection['outputBytes']
    if label in ('picture', 'pipeline') and request.get('revision', {}).get('mode') == 'initial-long':
        written -= retained_long_disk(request)  # Completed captures already consume actual disk.
    if label.startswith('segment-picture-'):
        written = section_disk_bytes(request, label)
    reservation = max(DISK_RESERVATION_BYTES[settings.lane], written + projection['miscBytes'])
    return replace(settings, disk_expansion=True, disk_reservation_bytes=reservation)


def retained_long_disk(request: dict) -> int:
    """Bind any retained-byte subtraction to exact current selected geometry and output projection."""
    projection = request['diskProjection']
    retained = projection.get('retainedFrameBytes', 0)
    require(type(retained) is int and retained >= 0, 'invalid retained Long disk projection')
    if retained == 0:
        return 0  # Historical requests reserve their original complete encoded output.
    from studio.native_long_scope import selected_windows
    canvas = request['revision']['canvas']
    require(all(type(canvas.get(key)) is int and canvas[key] > 0
                for key in ('width', 'height', 'totalFrames')), 'invalid retained Long disk canvas')
    frames = sum(row['endFrame'] - row['startFrame'] for row in selected_windows(request))
    pixels = canvas['width'] * canvas['height']
    require(retained == frames * pixels * 4
            and projection['outputBytes'] == (canvas['totalFrames'] * pixels + 3) // 4 + retained,
            'invalid retained Long disk projection')
    return retained


def section_disk_bytes(request: dict, label: str) -> int:
    """Reserve retained JPEG bytes for one window; the owner adds encoded/media headroom."""
    from studio.native_segments.owners import segment_phase
    index = segment_phase('-'.join(label.split('-')[:3]))
    require(index is not None, 'invalid section owner disk label')
    revision = request['revision']
    require(index < len(revision['renderWindows']), 'section disk index exceeds window inventory')
    window, canvas = revision['renderWindows'][index], revision['canvas']
    require(all(type(canvas.get(key)) is int and canvas[key] > 0
                for key in ('width', 'height', 'totalFrames'))
            and all(type(window.get(key)) is int for key in ('startFrame', 'endFrame'))
            and 0 <= window['startFrame'] < window['endFrame'] <= canvas['totalFrames'],
            'invalid section disk geometry')
    frames = window['endFrame'] - window['startFrame']
    return frames * canvas['width'] * canvas['height'] * 4


def short_owner_disk(settings: NativeRunConfig, request: dict, label: str) -> NativeRunConfig:
    """Reserve retained full-frame storage before a standard Short picture or draft owner starts.

    Four bytes per pixel bounds the JPEG screenshot inventory conservatively;
    the existing heavy reservation remains additional room for encoding/muxing.
    Reused JPEGs are copied, so revisions need the same additional reservation.
    """
    if request.get('sourceCacheMode') in ('acquire-content-store', 'acquire-content-store-sequential-sdr'):
        projection = request.get('diskProjection')
        require(isinstance(projection, dict) and all(type(projection.get(key)) is int and projection[key] >= 0
                                                   for key in ('sampleBytes', 'outputBytes', 'miscBytes')),
                'Short content source acquisition requires its disk projection')
        settings = replace(settings, disk_expansion=True)
        if label in ('capture', 'preview') or label.startswith('preview-picture-'):
            reservation = max(DISK_RESERVATION_BYTES[settings.lane],
                              projection['sampleBytes'] + projection['miscBytes'])
            settings = replace(settings, disk_reservation_bytes=reservation)
    if label not in ('pipeline', 'picture', 'draft') or request.get('pictureDonor') \
            or request.get('captureMode') != 'cached-native-batches':
        return settings
    from cut_preview_io import bound_json
    canvas = bound_json(Path(request['project']) / 'SHORT-PROJECT.json')['canvas']
    frames = canvas['totalFrames']
    require(type(frames) is int and 0 < frames <= 10800, 'Short retained frame count is invalid')
    return replace(settings, disk_reservation_bytes=frames * 1080 * 1920 * 4
                   + DISK_RESERVATION_BYTES['heavy'])


def short_disk_projection(canvas: dict) -> dict:
    """Conservatively project retained pictures and bounded QC scratch for source admission.

    The source owner grows its cache reservation separately. Continuous disk guards
    remain authoritative; these figures do not predict JPEG compression or speed.
    """
    frames = canvas['totalFrames']
    require(type(frames) is int and 0 < frames <= 10800, 'Short disk projection needs a bounded frame count')
    pixels = 1080 * 1920 * 4
    return {'sampleBytes': min(2 * frames + 1, 3000) * pixels * 3,
            'outputBytes': frames * pixels, 'miscBytes': DISK_RESERVATION_BYTES['heavy']}
