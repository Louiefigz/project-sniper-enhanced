"""Supervised, sealed section owners and exact-input recovery through existing export history.

Every completed window is sealed only after NativeRun verifies owned cleanup. A
new attempt may restore registered exact-plan seals. Cross-generation reuse
requires an independently revalidated scoped relation to preserved source snapshots. Initial Long dispatch uses the existing qualified host pool.
One transient retry uses the inherited production authority; this module never
mints a fresh counter or silently reruns deterministic errors.
"""
from __future__ import annotations

import re
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_export_history import known_attempts
from studio.native_runtime import digest
from studio.native_stage_evidence import StageEvidence, read_stage, require, seal_stage

STATUS = 'native-segment-window-complete'
WINDOW_MODES = frozenset({'segments', 'full-render', 'initial-long'})
PHASE = re.compile(r'segment-picture-(0|[1-9][0-9]{0,2})')


def segment_phase(phase: str) -> int | None:
    """The window index of a segment phase name, or None."""
    match = PHASE.fullmatch(phase)
    return int(match[1]) if match and int(match[1]) < 768 else None


def segment_output(phase: str) -> str:
    """The one owner-bound receipt a window owner publishes."""
    require(segment_phase(phase) is not None, 'invalid segment phase')
    return f'{phase}.json'


def revision_windows(request: dict) -> list[dict]:
    """The admitted render windows of a segment revision (empty for any other request)."""
    revision = request.get('revision')
    return revision['renderWindows'] if revision and revision['mode'] in WINDOW_MODES else []


def generates_picture(request: dict) -> bool:
    """Whether a launch generates picture: every request except an exact whole-picture revision reuse."""
    revision = request.get('revision')
    return not revision or revision['mode'] != 'picture-reuse'


def artifacts(root: Path, phase: str) -> dict[str, Path]:
    """Receipt, segment media and every captured dependency probe of one window."""
    value = bound_json(root / segment_output(phase))
    files = {'receipt': root / segment_output(phase), 'media': Path(value['piece']['path'])}
    from studio.native_segments.probe import probe_artifacts
    files.update(probe_artifacts(value))
    files.update({f'probe{index}': Path(row['path']) for index, row in enumerate(value['probes'])})
    if value.get('audio'):
        files['audio'] = Path(value['audio']['path'])
    from studio.native_segments.frame_capture import frame_artifacts
    files.update(frame_artifacts(value))
    return files


def seal_window(pipeline: object, phase: str, label: str) -> None:
    """Seal a completed window with the successful owner's receipt."""
    root, request = pipeline.root, pipeline.request
    spec = StageEvidence(phase, Path(request['project']), root, root / 'export-request.json',
                         root / f'{label}.render.json', request['pins'], artifacts(root, phase), STATUS)
    seal_stage(spec)
    _record, pins = read_stage(root / f'{phase}-stage.json', request['pins'], phase)
    pipeline.evidence.update(pins)


def attempt_window(pipeline: object, phase: str, label: str) -> Exception | None:
    """Run one window owner; return its failure instead of raising it."""
    from studio.native_short_pipeline import NativeStageFailure
    try:
        pipeline.supervise(label, pipeline.worker(phase), segment_output(phase), STATUS)
    except NativeStageFailure as failure:
        return failure
    return None


def supervise_window(pipeline: object, phase: str, retries: list[int]) -> str:
    """Retry one transient failure only when the inherited durable authority permits it."""
    from time import sleep
    from studio.native_budget_sections import section_retry_allowed
    failure = attempt_window(pipeline, phase, phase)
    if failure is None:
        return phase
    if not section_retry_allowed(pipeline.request, phase, failure):
        raise failure
    sleep(1)  # First exponential-backoff step; authority allows only one transient retry.
    label = phase + '-retry-1'
    failure = attempt_window(pipeline, phase, label)
    if failure is not None:
        raise failure
    return label


def run_revision_windows(pipeline: object) -> None:
    """Render or restore every window; Long dispatch uses measured pool capacity."""
    if pipeline.request.get('revision', {}).get('mode') == 'initial-long':
        from studio.native_segments.supervision import run_sections
        run_sections(pipeline)
        return
    retries = [0]
    for window in revision_windows(pipeline.request):
        phase = f"segment-picture-{window['index']}"
        if restore_window(pipeline, phase):
            continue
        seal_window(pipeline, phase, supervise_window(pipeline, phase, retries))


def matching_seal(file: Path, request: dict, window: dict) -> bool:
    """Whether an earlier window seal names this revision plan, window and project."""
    record = bound_json(file)
    receipt = record.get('artifacts', {}).get('receipt', {})
    if record.get('project') != request['project'] or 'path' not in receipt:
        return False
    value = bound_json(Path(receipt['path']), receipt['sha256'])
    return value.get('planIdentity') == request['revision']['identity'] and value.get('window') == window


def bind_window_recovery(request: dict, attempts: list[Path] | None = None) -> dict:
    """Pin exact completed windows of earlier attempts of this revision before publication."""
    windows = {f"segment-picture-{row['index']}": row for row in revision_windows(request)}
    donors, pins, selected = dict(request.get('revision', {}).get('windowDonors', {})), {}, set()
    known = known_attempts(request)
    require(attempts is None or set(attempts) <= set(known), 'section resume requires registered attempts')
    seals = [file for attempt in sorted(known if attempts is None else attempts)
             for file in attempt_window_seals(attempt, known)]
    for file in seals:
        phase = file.name.removesuffix('-stage.json')
        if phase in selected or phase not in windows or not matching_seal(file, request, windows[phase]):
            continue
        _record, retained = read_stage(file, bound_json(file)['inputs'], phase)  # corrupt seals refuse
        donors[phase] = str(file)
        selected.add(phase)
        pins.update(retained)
    if donors:
        request['revision'] = {**request['revision'], 'windowDonors': donors}
        request['pins'].update(pins)
    return request


def attempt_window_seals(attempt: Path, known: list[Path]) -> list[Path]:
    """Retain exact ancestor seals when this attempt restored a window instead of resealing it."""
    original = bound_json(attempt / 'export-request.json')
    direct = set(attempt.glob('segment-picture-*-stage.json'))
    inherited = original.get('revision', {}).get('windowDonors', {})
    require(isinstance(inherited, dict), 'invalid inherited section donor map')
    for phase, filename in inherited.items():
        if original.get('sectionRepair') or original.get('sectionIntegrations') or attempt / f'{phase}-stage.json' in direct:
            continue
        file = Path(filename)
        require(segment_phase(phase) is not None and file.name == f'{phase}-stage.json'
                and file.parent in known and original['pins'].get(str(file)) == digest(file),
                'section donor ancestor is unregistered or changed')
        direct.add(file)
    return sorted(direct)


def restore_window(pipeline: object, phase: str) -> bool:
    """Copy an exact earlier window (media and probes) into this attempt; never write the donor."""
    from studio.native_short_picture_reuse import copy_picture
    source = pipeline.request['revision'].get('windowDonors', {}).get(phase)
    if source is None:
        return False
    record, pins = read_stage(Path(source), bound_json(Path(source))['inputs'], phase)
    require(all(pipeline.request['pins'].get(file) == sha for file, sha in pins.items()), 'unpinned window donor')
    value = bound_json(Path(record['artifacts']['receipt']['path']), record['artifacts']['receipt']['sha256'])
    if value.get('planIdentity') != pipeline.request['revision']['identity']:
        require(bool(pipeline.request.get('sectionRepair') or pipeline.request.get('sectionIntegrations')),
                'section donor belongs to another plan')
        return False  # Cross-generation picture receives fresh PCM under its current owner.
    target = pipeline.root / f'{phase}-restored'
    target.mkdir()
    moved = {}
    for name, row in record['artifacts'].items():
        if name != 'receipt' and not name.startswith('retainedFrame'):
            moved[row['path']] = str(target / f"{name}{Path(row['path']).suffix}")
            copy_picture(Path(row['path']), Path(moved[row['path']]), row['sha256'])
    value = {**value, 'restoredFrom': source, 'piece': {**value['piece'], 'path': moved[value['piece']['path']]},
             'probes': [{**row, 'path': moved[row['path']]} for row in value['probes']]}
    if value.get('audio'):
        value['audio'] = {**value['audio'], 'path': moved[value['audio']['path']]}
    write_new(pipeline.root / segment_output(phase), value)
    pipeline.evidence.update({**pins, str(pipeline.root / segment_output(phase)):
                              digest(pipeline.root / segment_output(phase))})
    pipeline.stages.append({'phase': phase + '-reused', 'receipt': source, 'sha256': digest(Path(source)),
                            'status': STATUS, 'elapsedSeconds': 0})
    return True


def current_window(request: dict, phase: str) -> dict:
    """Assembly-side read: this attempt's sealed window or its exact restored copy, bytes verified."""
    root = Path(request['output'])
    direct = root / f'{phase}-stage.json'
    donor = None if direct.exists() else request['revision'].get('windowDonors', {}).get(phase)
    seal = Path(donor) if donor else direct
    record, pins = read_stage(seal, bound_json(seal)['inputs'], phase)
    require(record['successStatus'] == STATUS, 'segment window status differs')
    receipt = record['artifacts']['receipt']
    sealed = bound_json(Path(receipt['path']), receipt['sha256'])
    require(sealed.get('planIdentity') == request['revision']['identity'],
            'repaired section awaits its current owner seal')
    require(bool(donor) or (record['inputs'] == request['pins'] and record['project'] == request['project']),
            'current section seal has different admitted inputs')
    value = bound_json(root / segment_output(phase)) if donor else sealed
    index = segment_phase(phase)
    require(index is not None and value['window'] == request['revision']['renderWindows'][index]
            and value['planIdentity'] == request['revision']['identity'],
            'segment window belongs to another plan or generation')
    require(digest(Path(value['piece']['path'])) == sealed['piece']['sha256'] == value['piece']['sha256'],
            'segment window media changed')
    if sealed.get('audio'):
        require(digest(Path(value['audio']['path'])) == sealed['audio']['sha256'] == value['audio']['sha256'],
                'segment window audio changed')
    if donor:
        require(all(request['pins'].get(file) == sha for file, sha in pins.items()), 'unpinned window donor')
    from studio.native_segments.probe import require_dependency_probe
    require_dependency_probe(request, phase, value, record)
    return value
