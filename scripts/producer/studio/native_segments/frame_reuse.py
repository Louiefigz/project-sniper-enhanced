"""Proof-first retained Long screenshots; public capture and disk admission remain separate.

Only a registered immutable repair parent may donate frames. A dirty encoder
window still needs one complete new encode and fresh audio/reviews. This helper
never executes media, adopts Short limits, or grants a render/disk reservation.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_retained_frames import CaptureContract, frame_partition, read_frame_inventory
from studio.native_runtime import digest
from studio.native_segments.compatibility import _seal, validate_repair
from studio.native_segments.long_plan import MAX_WINDOW_FRAMES, identity
from studio.native_segments.owners import current_window, segment_phase
from studio.native_segments.probe import dependency_frames
from studio.native_stage_evidence import read_stage, require

KIND = 'native-long-retained-frame-repair'
MAX_MANIFEST_BYTES = 1024 * 1024


def capture_contract(request: dict, window: dict, manifest: Path) -> CaptureContract:
    """Keep one absolute bounded Long window and a raw-pixel-sized JPEG ceiling."""
    canvas = request['revision']['canvas']
    require(all(type(canvas.get(key)) is int and canvas[key] > 0 for key in ('width', 'height')),
            'invalid retained Long canvas')
    return CaptureContract(manifest.parent / 'frames', canvas, (window['startFrame'], window['endFrame']),
                           (MAX_WINDOW_FRAMES, canvas['width'] * canvas['height'] * 4))


def read_capture(request: dict, window: dict, pin: dict) -> dict:
    """Read a fixed-name bounded capture manifest and every canonical JPEG it names."""
    require(type(pin) is dict and set(pin) == {'path', 'sha256'}, 'invalid retained capture pin')
    file = Path(pin['path'])
    require(file.name == 'retained-frames.json' and file.parent.parent == Path(request['output']),
            'retained capture manifest escapes its original window owner')
    value = bound_json(file, pin['sha256'], maximum=MAX_MANIFEST_BYTES)
    read_frame_inventory(value, capture_contract(request, window, file))
    return value


def baseline_capture(original: dict, phase: str, depth: int = 0) -> tuple[dict | None, dict]:
    """Absence permits a full capture; any present seal or claimed capture must validate."""
    require(type(depth) is int and 0 <= depth <= 8, 'retained frame lineage exceeds bounded proof reader')
    file = _seal(original, phase)
    if file is None:
        require(not (Path(original['output']) / f'{phase}-stage.json').is_symlink(), 'unsafe prior window seal')
        orphan = Path(original['output']) / f'{phase}.json'
        require(not orphan.exists() and not orphan.is_symlink(), 'unsealed prior window cannot donate frames')
        return None, {}
    value = current_window(original, phase)
    record, pins = read_stage(file, bound_json(file)['inputs'], phase)
    sealed = record['artifacts']['receipt']
    value = bound_json(Path(sealed['path']), sealed['sha256'])
    if value.get('retainedCaptureDonor') is not None:
        return _relay_baseline(record, value, phase, (pins, depth))
    pin = value.get('retainedFrames')
    if pin is None:
        require('retainedFrames' not in record['artifacts'], 'sealed retained capture is missing from its receipt')
        return None, {}
    require(pin == record['artifacts'].get('retainedFrames'), 'retained capture manifest is not sealed')
    captured_request = bound_json(Path(record['request']['path']), record['request']['sha256'])
    capture = read_capture(captured_request, value['window'], pin)
    require(all(record['artifacts'].get(f"retainedFrame{row['frame']}") ==
                {'path': row['path'], 'sha256': row['sha256']} for row in capture['frames']),
            'retained JPEG inventory is not fully sealed')
    if any(row['origin'] == 'retained' for row in capture['frames']):
        from studio.native_segments.frame_capture import read_frame_plan
        prior_plan = read_frame_plan(captured_request, phase)
        proof = value.get('retainedFrameProof')
        require(type(prior_plan) is dict and prior_plan.get('phase') == phase
                and type(proof) is dict and proof == record['artifacts'].get('retainedFrameProof'),
                'retained baseline lacks original sealed comparison authority')
        expected = _checked_capture(captured_request, prior_plan, pin, depth + 1)
        require(bound_json(Path(proof['path']), proof['sha256']) == expected, 'original retained comparison changed')
    return {'seal': {'path': str(file), 'sha256': digest(file)}, 'manifest': pin,
            'window': value['window'], 'frames': capture['frames']}, pins


def _relay_baseline(record: dict, value: dict, phase: str, context: tuple[dict, int]) -> tuple[dict | None, dict]:
    """Follow only a sealed current owner's exact admitted complete-window donor."""
    pins, depth = context
    require('retainedFrames' not in value and 'retainedFrameProof' not in value,
            'retained capture has ambiguous inline and relay origins')
    request = bound_json(Path(record['request']['path']), record['request']['sha256'])
    donor = value['retainedCaptureDonor']
    require(type(donor) is dict and set(donor) == {'path', 'sha256'}
            and donor['path'] == request['revision'].get('windowDonors', {}).get(phase)
            and request['pins'].get(donor['path']) == donor['sha256'], 'retained capture relay was not admitted')
    file = Path(donor['path'])
    raw = bound_json(file, donor['sha256'])
    previous, inherited = read_stage(file, raw['inputs'], phase)
    require(all(request['pins'].get(name) == sha for name, sha in inherited.items()), 'unpinned retained capture relay')
    prior = bound_json(Path(previous['request']['path']), previous['request']['sha256'])
    baseline, closure = baseline_capture(prior, phase, depth + 1)
    require(baseline is not None, 'declared retained capture relay has no baseline')
    return baseline, {**pins, **inherited, **closure}


def _check_frames(window: dict, unchanged: list[int], project: Path) -> list[int]:
    """Recapture dependency states and both sides/interior of every unchanged interval."""
    points = set(dependency_frames(window, project))
    retained = set(unchanged)
    starts = [frame for frame in unchanged if frame - 1 not in retained]
    ends = [frame for frame in unchanged if frame + 1 not in retained]
    points.update(point for start, end in zip(starts, ends) for point in (start, end, (start + end) // 2))
    return sorted(points.intersection(unchanged))


def _plan(request: dict, phase: str, baseline: dict | None) -> dict:
    """Select exact dirty capture frames; global/unknown dependencies keep full capture."""
    index = segment_phase(phase)
    require(index is not None and index < len(request['revision']['renderWindows']), 'invalid retained frame phase')
    window = request['revision']['renderWindows'][index]
    bounds = [window['startFrame'], window['endFrame']]
    all_frames, _empty = frame_partition(tuple(bounds), [bounds], MAX_WINDOW_FRAMES)
    dependency = request['revision']['dependency']
    result = {'schemaVersion': 1, 'kind': KIND, 'phase': phase, 'planIdentity': request['revision']['identity'],
              'window': window, 'frameRange': bounds, 'mode': 'full-capture', 'baseline': baseline,
              'captureFrames': all_frames, 'copyFrames': [], 'checkFrames': []}
    if baseline is None:
        return {**result, 'reason': 'parent has no sealed retained JPEG baseline'}
    if dependency['semanticGlobal'] or [baseline['window']['startFrame'], baseline['window']['endFrame']] != bounds:
        return {**result, 'reason': 'global dependency or changed absolute window geometry'}
    dirty, unchanged = frame_partition(tuple(bounds), dependency['semanticBounds'], MAX_WINDOW_FRAMES)
    if not unchanged:
        return {**result, 'reason': 'every frame in the encoder window is affected'}
    checks = _check_frames(window, unchanged, Path(request['project']))
    copies = sorted(set(unchanged) - set(checks))
    return {**result, 'mode': 'retained-frames', 'reason': 'validated local dependency with current recapture checks',
            'captureFrames': sorted(set(dirty) | set(checks)), 'copyFrames': copies, 'checkFrames': checks}


def frame_reuse_plan(request: dict, phase: str, depth: int = 0) -> dict:
    """Derive a plan and pins before publication; no frame is consumed or reservation granted."""
    require(type(depth) is int and 0 <= depth <= 8, 'retained frame lineage exceeds bounded proof reader')
    original = validate_repair(request)
    index = segment_phase(phase)
    require(index is not None and index < len(request['revision']['renderWindows']), 'invalid baseline frame phase')
    baseline, pins = (baseline_capture(original, phase, depth) if index < len(original['revision']['renderWindows'])
                      else (None, {}))
    result = _plan(request, phase, baseline)
    result['requiredPins'] = pins
    result['identity'] = identity(result)
    return result


def validate_frame_reuse(request: dict, phase: str, plan: dict, depth: int = 0) -> None:
    """Recompute locality and original owner proof, requiring every donor pin before use."""
    expected = frame_reuse_plan(request, phase, depth)
    require(plan == (expected if 'requiredPins' in plan else compact_frame_plan(expected)),
            'retained frame repair plan changed')
    require(all(request['pins'].get(file) == sha for file, sha in expected['requiredPins'].items()),
            'retained frame repair evidence was not admitted')


def compact_frame_plan(plan: dict) -> dict:
    """Store the full input map once in request pins, binding each plan to its exact closure digest."""
    result = {key: value for key, value in plan.items() if key not in ('requiredPins', 'identity')}
    result['requiredPinsIdentity'] = identity(plan['requiredPins'])
    result['identity'] = identity(result)
    return result


def validate_frame_capture(request: dict, phase: str, plan: dict, pin: dict) -> dict:
    """Verify completed current capture/copy partition and actual unchanged pixel equality.

    The owner must additionally encode the entire window and seal this manifest,
    every JPEG, the current request and this plan after clean supervised disposal.
    """
    require(plan.get('phase') == phase, 'retained comparison phase differs')
    return _checked_capture(request, plan, pin, 0)


def _checked_capture(request: dict, plan: dict, pin: dict, depth: int) -> dict:
    """Reopen an exact capture partition, keeping repeated repair lineage recursion bounded."""
    validate_frame_reuse(request, plan['phase'], plan, depth)
    value = read_capture(request, plan['window'], pin)
    captured = [row['frame'] for row in value['frames'] if row['origin'] == 'captured']
    copied = [row['frame'] for row in value['frames'] if row['origin'] == 'retained']
    require(captured == plan['captureFrames'] and copied == plan['copyFrames'], 'retained capture partition differs')
    baseline = {row['frame']: row['sha256'] for row in (plan['baseline'] or {}).get('frames', [])}
    require(all(row['sha256'] == baseline[row['frame']] for row in value['frames']
                if row['frame'] in set(plan['copyFrames'] + plan['checkFrames'])),
            'current unchanged capture or retained copy differs from original pixels')
    return {'schemaVersion': 1, 'kind': 'native-long-retained-frame-comparison', 'planIdentity': plan['identity'],
            'capture': pin, 'checkedFrames': plan['checkFrames'], 'copiedFrames': plan['copyFrames'],
            'passed': True, 'editorialApproval': False, 'runtimeQualification': 'not-established'}
