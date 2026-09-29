"""Bind Long frame reuse before publication and verify actual capture before sealing."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import MAX_JSON, bound_json, write_new
from cross_runtime_canonical_json import canonical_compact_json
from studio.native_runtime import digest
from studio.native_stage_evidence import require


def bind_frame_reuse(request: dict) -> None:
    """Freeze dirty-window plans and every original proof pin before any window owner launches."""
    if request.get('revision', {}).get('mode') != 'initial-long' or not request.get('sectionRepair'):
        return
    from studio.native_long_scope import selected_windows
    from studio.native_segments.frame_reuse import frame_reuse_plan, compact_frame_plan
    from studio.native_segments.compatibility import _merge_pins
    plans = {}
    for window in selected_windows(request):
        phase = f"segment-picture-{window['index']}"
        if phase in request['revision'].get('windowDonors', {}):
            continue
        plan = frame_reuse_plan(request, phase)
        _merge_pins(request, plan['requiredPins'])
        file = Path(request['output']) / f'{phase}-frame-plan.json'
        value = compact_frame_plan(plan)
        require(len(canonical_compact_json(value).encode()) + 1 <= 1024 * 1024,
                'retained frame plan exceeds bounded sidecar size')
        write_new(file, value)
        sha = digest(file)
        request['pins'][str(file)] = sha
        plans[phase] = {'path': str(file), 'sha256': sha}
    request['sectionFrameReuse'] = plans
    require(len(canonical_compact_json(request).encode()) + 1 <= MAX_JSON,
            'retained frame request exceeds existing JSON bound before publication')


def read_frame_plan(request: dict, phase: str) -> dict | None:
    """Resolve one immutable bounded plan; historical helper fixtures may contain inline plans."""
    value = request.get('sectionFrameReuse', {}).get(phase)
    if value is None:
        return value
    require(type(value) is dict, 'invalid retained frame plan reference')
    if 'requiredPins' in value:
        return value
    require(type(value) is dict and set(value) == {'path', 'sha256'}, 'invalid retained frame plan reference')
    file = Path(value['path'])
    require(file.name == f'{phase}-frame-plan.json'
            and request['pins'].get(str(file)) == value['sha256'], 'retained frame plan was not admitted')
    return bound_json(file, value['sha256'], maximum=1024 * 1024)


def require_frame_reuse(request: dict, phase: str) -> None:
    """Recompute the frozen local capture relation before invoking the Node renderer."""
    if request.get('revision', {}).get('mode') != 'initial-long' or not request.get('sectionRepair'):
        return
    from studio.native_segments.frame_reuse import validate_frame_reuse
    plan = read_frame_plan(request, phase)
    require(isinstance(plan, dict), 'Long repair lacks its published retained frame plan')
    validate_frame_reuse(request, phase, plan)


def finish_frame_capture(request: dict, phase: str, receipt: dict) -> dict:
    """Validate actual sessions, complete frame inventory and any unchanged comparison evidence."""
    if request['revision']['mode'] != 'initial-long':
        return {}
    from studio.native_segments.frame_reuse import read_capture, validate_frame_capture
    pin = receipt.get('retainedFrames')
    require(isinstance(pin, dict), 'Long window omitted retained capture inventory')
    value = read_capture(request, receipt['window'], pin)
    require([row['sha256'] for row in value['frames']] == receipt['frameSha256'],
            'retained capture hashes differ from encoded window inventory')
    result = {'retainedFrames': pin}
    plan = read_frame_plan(request, phase)
    if plan is None:
        require(not request.get('sectionRepair') and all(row['origin'] == 'captured' for row in value['frames']),
                'retained frames lack their original repair proof')
        return result
    proof = validate_frame_capture(request, phase, plan, pin)
    file = Path(pin['path']).parent / 'retained-frame-proof.json'
    write_new(file, proof)
    return {**result, 'retainedFrameProof': {'path': str(file), 'sha256': digest(file)}}


def frame_artifacts(value: dict) -> dict[str, Path]:
    """Seal every completed local screenshot and comparison with the existing StageEvidence."""
    pin = value.get('retainedFrames')
    if pin is None:
        return {}
    file = Path(pin['path'])
    manifest = bound_json(file, pin['sha256'], maximum=1024 * 1024)
    files = {'retainedFrames': file}
    files.update({f"retainedFrame{row['frame']}": Path(row['path']) for row in manifest['frames']})
    if value.get('retainedFrameProof'):
        proof = value['retainedFrameProof']
        require(digest(Path(proof['path'])) == proof['sha256'], 'retained comparison changed before sealing')
        files['retainedFrameProof'] = Path(proof['path'])
    return files


def relay_frame_capture(record: dict, value: dict, donor: str) -> dict:
    """Preserve original capture proof as admitted input; never copy JPEGs into false owner paths."""
    if not value.get('retainedFrames') and not value.get('retainedCaptureDonor'):
        return value
    require(not (value.get('retainedFrames') and value.get('retainedCaptureDonor')),
            'retained capture has ambiguous inline and relay origins')
    if value.get('retainedFrames'):
        require(value['retainedFrames'] == record['artifacts'].get('retainedFrames'),
                'retained donor capture is not sealed')
    result = {key: item for key, item in value.items() if key not in ('retainedFrames', 'retainedFrameProof')}
    result['retainedCaptureDonor'] = {'path': donor, 'sha256': digest(Path(donor))}
    return result
