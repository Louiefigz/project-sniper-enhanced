"""Owned continuous Long review packages and exact registered retained-package reads."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_export_history import known_attempts
from studio.native_runtime import digest
from studio.native_segments.long_plan import identity
from studio.native_segments.review_media import STATUS, source_state
from studio.native_segments.review_scopes import phase_for, request_scope
from studio.native_stage_evidence import StageEvidence, read_stage, require, seal_stage


def receipt_pin(file: Path) -> dict:
    """Use the existing immutable artifact pin shape for host review dispatch."""
    return {'path': str(file), 'sha256': digest(file), 'bytes': file.stat().st_size}


def source_pins(request: dict, scope: dict) -> dict[str, str]:
    """Add dynamic sealed-media and whole-master bytes to the owner before/after inventory."""
    _snapshot, values, prepared = source_state(request, scope)
    files = [Path(request['output']) / 'prepared-audio.json', Path(prepared['masterReceipt'])]
    master = bound_json(Path(prepared['masterReceipt']))
    files.extend((Path(master['output']), Path(prepared['reference'])))
    for value in values:
        files.extend((Path(value['piece']['path']), Path(value['audio']['path'])))
        phase = f"segment-picture-{value['window']['index']}"
        direct = Path(request['output']) / f'{phase}-stage.json'
        files.append(direct if direct.exists() else Path(request['revision']['windowDonors'][phase]))
    return {str(file): digest(file) for file in files}


def seal_package(pipeline: object, phase: str, label: str) -> Path:
    """Only successful owned cleanup permits an immutable reusable playback receipt."""
    root, request = pipeline.root, pipeline.request
    file = root / f'{phase}.json'
    value = bound_json(file)
    files = {'receipt': file, 'picture': Path(value['picture']['path']),
             'audio': Path(value['audio']['path']), 'mux': Path(value['mux']['path']),
             'media': Path(value['media']['path'])}
    spec = StageEvidence(phase, Path(request['project']), root, root / 'export-request.json',
                         root / f'{label}.render.json', request['pins'], files, STATUS)
    seal_stage(spec)
    seal = root / f'{phase}-stage.json'
    _record, pins = read_stage(seal, request['pins'], phase)
    pipeline.evidence.update(pins)
    return file


def read_package(request: dict, scope_id: str, pin: dict | None = None) -> dict:
    """Recheck completed owner, original sources and exact current media/master identity."""
    scope = request_scope(request, scope_id)
    phase = phase_for(scope_id)
    file = Path(pin['path']) if pin else Path(request['output']) / f'{phase}.json'
    require(file.name == f'{phase}.json', 'review receipt does not match its frozen scope')
    if pin is not None:
        require(receipt_pin(file) == pin, 'review package receipt changed')
    from studio.native_segments.compatibility import _parent
    original = _parent(file.parent)
    require(original.get('productionBudget', {}).get('batchId') == request.get('productionBudget', {}).get('batchId')
            and original.get('productionBudget', {}).get('clipId') == request.get('productionBudget', {}).get('clipId'),
            'review package belongs to another production authority')
    record, _pins = read_stage(file.parent / f'{phase}-stage.json', original['pins'], phase)
    require(record['successStatus'] == STATUS and record['artifacts']['receipt']['path'] == str(file),
            'review package seal names another receipt')
    value = bound_json(file, record['artifacts']['receipt']['sha256'])
    validate_receipt(value, original, request_scope(original, scope_id))
    expected = source_state(request, scope)[0]
    require(value['sources'] == expected and value['inputIdentity'] == identity(expected),
            'review package media, source, transition or master generation changed')
    return value


def validate_receipt(value: dict, original: dict, scope: dict) -> None:
    """Require technical package proofs without interpreting them as human approval."""
    require(value.get('kind') == 'native-long-review-package' and value.get('schemaVersion') == 1
            and value.get('status') == STATUS and value.get('scope') == scope,
            'invalid continuous review package receipt')
    require(value['request'] == str(Path(original['output']) / 'export-request.json')
            and value['requestSha256'] == digest(Path(value['request'])), 'review package request changed')
    require(value['sources'] == source_state(original, request_scope(original, scope['id']))[0],
            'original review package source proof changed')
    media = value['media']
    require(value['additionalPictureEncodes'] == 0 and value['audioCategory'] == 'derived-review-only'
            and value['assembly']['piecePayloadsIdentical'] is True
            and media['audiblePathAacEncodes'] == 1 and media['fullAudioVideoDecodePassed'] is True
            and media['color']['aacPacketsIdentical'] is True,
            'continuous review package lacks packet/decode/color proof')
    require([media['startFrame'], media['endFrameExclusive']] == scope['frameRange']
            and media['audioClock']['presentedSamples'] == value['audio']['samples'],
            'review package audio clock differs from its absolute scope')


def retained_package(request: dict, scope_id: str) -> dict | None:
    """Reuse exact registered completed bytes; present corrupt evidence never becomes a rerender."""
    phase = phase_for(scope_id)
    current = Path(request['output']) / f'{phase}-stage.json'
    if current.exists():
        file = current.with_name(f'{phase}.json')
        read_package(request, scope_id, receipt_pin(file))
        return receipt_pin(file)
    expected = None
    for root in reversed(package_attempts(request)):
        file, seal = root / f'{phase}.json', root / f'{phase}-stage.json'
        if not seal.exists():
            continue
        if expected is None:
            expected = identity(source_state(request, request_scope(request, scope_id))[0])
        record, _pins = read_stage(seal, bound_json(root / 'export-request.json')['pins'], phase)
        value = bound_json(file, record['artifacts']['receipt']['sha256'])
        if value.get('inputIdentity') == expected:
            pin = receipt_pin(file)
            read_package(request, scope_id, pin)
            return pin
    return None


def package_attempts(request: dict) -> list[Path]:
    """Discover only registered same-project attempts and explicitly admitted scoped ancestors."""
    from studio.native_long_integration import integration_source
    paths = set(known_attempts(request))
    for pointer in request.get('sectionIntegrations', []):
        original, _row = integration_source(request, pointer)
        paths.update(known_attempts(original))
    repair = request.get('sectionRepair')
    if repair:
        from studio.native_segments.compatibility import _parent
        original = _parent(Path(repair['parentAttempt']), repair['parentRequestSha256'])
        paths.update(known_attempts(original))
    return sorted(paths)


def ensure_package(pipeline: object, scope_id: str) -> dict:
    """Create one owned package outside task transactions, or return exact retained proof."""
    request = pipeline.request
    retained = retained_package(request, scope_id)
    if retained:
        return retained
    require(request.get('productionBudget', {}).get('familyInvocation'),
            'new review packages require the original counted section family')
    phase = phase_for(scope_id)
    pipeline.evidence.update(source_pins(request, request_scope(request, scope_id)))
    label = launch_package(pipeline, phase)
    file = seal_package(pipeline, phase, label)
    pin = receipt_pin(file)
    read_package(request, scope_id, pin)
    return pin


def launch_package(pipeline: object, phase: str) -> str:
    """Retry only proven transient failures under the original shared retry allowance."""
    from time import sleep
    from studio.native_budget_sections import section_retry_allowed
    from studio.native_short_pipeline import NativeStageFailure
    retain_partial_receipt(pipeline.root, phase)
    try:
        pipeline.supervise(phase, pipeline.worker(phase), f'{phase}.json', STATUS)
        return phase
    except NativeStageFailure as error:
        if not section_retry_allowed(pipeline.request, phase, error):
            raise
    sleep(1)
    retain_partial_receipt(pipeline.root, phase)
    label = phase + '-retry-1'
    pipeline.supervise(label, pipeline.worker(phase), f'{phase}.json', STATUS)
    return label


def retain_partial_receipt(root: Path, phase: str) -> None:
    """Preserve an unsealed failed candidate; never overwrite or discard completed proof."""
    import uuid
    file = root / f'{phase}.json'
    if not file.exists():
        return
    require(not (root / f'{phase}-stage.json').exists(), 'sealed package cannot be replaced')
    owners = [root / f'{phase}.render.json', root / f'{phase}-retry-1.render.json']
    rows = [bound_json(owner) for owner in owners if owner.exists()]
    require(bool(rows) and all(row.get('completedAt') and row.get('status') != STATUS for row in rows),
            'unsealed package still has unknown or successful owner outcome')
    file.rename(root / f'{phase}-unsealed-{uuid.uuid4().hex}.json')
