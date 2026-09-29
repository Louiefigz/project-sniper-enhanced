"""Cross-generation Long reuse through intact original stage proofs and scoped diffs.

The prior authored project is the immutable source snapshot: repairing it in place
invalidates its stage proofs and is refused. Only picture bytes transfer. Current
section audio, independent reviews and final assembly checks are always renewed.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_export_history import known_attempts
from studio.native_runtime import digest
from studio.native_segments.dependency import inventory, picture_changes
from studio.native_segments.long_plan import identity, repair_long_plan
from studio.native_stage_evidence import read_stage, require, verify_pins


def _implementation(request: dict) -> dict:
    """Admit the explicit implementation partition; old unpartitioned requests refuse."""
    pins = request.get('sectionImplementationPins')
    require(isinstance(pins, dict) and bool(pins),
            'section repair needs original implementation pins; preserve legacy attempts without repair reuse')
    require(all(request['pins'].get(file) == sha for file, sha in pins.items()),
            'section implementation pins differ from admitted inputs')
    return pins


def _project(request: dict) -> Path:
    """Require every current project file to match its immutable admitted pin."""
    root = Path(request['project'])
    observed = inventory(root)
    require(all(request['pins'].get(str(root / name)) == sha for name, sha in observed.items()),
            'repair source snapshot is not fully pinned or has changed')
    pinned = {Path(file).relative_to(root).as_posix(): sha for file, sha in request['pins'].items()
              if Path(file).is_relative_to(root)}
    require(pinned == observed, 'repair source snapshot inventory changed')
    return root


def _parent(attempt: Path, expected: str | None = None) -> dict:
    """Only an exact registered original request can introduce a repair lineage."""
    require(attempt.is_absolute() and attempt.resolve(strict=True) == attempt and not attempt.is_symlink(),
            'repair ancestor must be a canonical original attempt')
    original = bound_json(attempt / 'export-request.json', expected)
    require(original.get('adapter') == 'native-long'
            and original.get('revision', {}).get('mode') == 'initial-long'
            and original.get('output') == str(attempt), 'repair ancestor is not an initial Long attempt')
    require(attempt in known_attempts(original), 'repair ancestor is not registered')
    verify_pins(original['pins'])
    return original


def _plan(current: dict, original: dict) -> tuple[dict, dict]:
    """Recompute scoped compatibility from actual immutable projects and exact code/tool pins."""
    require(current.get('adapter') == 'native-long', 'repair requires the Long adapter')
    for field in ('runtime', 'tools'):
        require(current[field] == original[field], f'section repair changed {field}')
    implementation = _implementation(current)
    require(implementation == _implementation(original), 'section repair implementation or tool drift')
    verify_pins(implementation)
    old, new = _project(original), _project(current)
    changes = picture_changes(old, new)
    changes['pictureInputs'] = identity({'project': changes['pictureInputs'], 'implementation': implementation})
    canvas = bound_json(new / 'LONG-PROJECT.json')['canvas']
    return repair_long_plan(original['revision'], changes, canvas), changes


def _merge_pins(current: dict, retained: dict) -> None:
    """Preserve donor dependencies without overwriting a conflicting current input."""
    require(all(file not in current['pins'] or current['pins'][file] == sha for file, sha in retained.items()),
            'section donor dependency conflicts with current inputs')
    current['pins'].update(retained)


def _seal(original: dict, phase: str) -> Path | None:
    """A completed immediate-parent section, or its verified exact-resume ancestor."""
    root = Path(original['output'])
    direct = root / f'{phase}-stage.json'
    if direct.exists():
        return direct
    # Cross-generation copies require a new owner/PCM seal before they become donors.
    if not (root / f'{phase}.json').exists():
        return None
    donor = original['revision'].get('windowDonors', {}).get(phase)
    return Path(donor) if donor else None


def _donors(current: dict, original: dict) -> dict:
    """Retain only compatible complete sections, validating every original stage byte."""
    from studio.native_segments.owners import current_window
    donors = {}
    for window in current['revision']['renderWindows']:
        index, phase = window['index'], f"segment-picture-{window['index']}"
        if index >= len(original['revision']['renderWindows']) or original['revision']['renderWindows'][index] != window:
            continue
        file = _seal(original, phase)
        if file is None:
            continue
        value = current_window(original, phase)
        require(value['window'] == window, 'repair donor section identity differs')
        _record, pins = read_stage(file, bound_json(file)['inputs'], phase)
        _merge_pins(current, pins)
        donors[phase] = str(file)
    return donors


def prepare_long_repair(current: dict, parent_attempt: Path) -> dict:
    """Bind reusable picture windows across preserved projects, without carrying approvals."""
    original = _parent(parent_attempt)
    result = {**current, 'pins': dict(current['pins'])}
    revision, changes = _plan(result, original)
    result['revision'] = revision
    result['sectionRepair'] = {'schemaVersion': 1, 'parentAttempt': str(parent_attempt),
                              'parentRequestSha256': digest(parent_attempt / 'export-request.json'),
                              'parentPlanIdentity': original['revision']['identity'],
                              'dependency': changes, 'audioPolicy': 'regenerate-current-section-pcm'}
    donors = _donors(result, original)
    result['revision'] = {**revision, 'windowDonors': donors}
    _merge_pins(result, {**original['pins'],
                        str(parent_attempt / 'export-request.json'): result['sectionRepair']['parentRequestSha256']})
    # Current review evidence must be admitted separately by the public entry point.
    for field in ('sectionReviews', 'previewReviews', 'previewFrom', 'pictureStage', 'verifyStage',
                  'sectionEarlyPreview', 'sectionReviewManifests', 'sectionProduction'):
        result.pop(field, None)
    return result


def validate_repair(request: dict) -> dict:
    """Recompute a registered repair relation without assuming any section completed."""
    repair = request.get('sectionRepair')
    require(isinstance(repair, dict) and repair.get('schemaVersion') == 1, 'missing section repair evidence')
    parent_file = Path(repair['parentAttempt']) / 'export-request.json'
    require(request['pins'].get(str(parent_file)) == repair['parentRequestSha256'],
            'repair parent request is not pinned')
    original = _parent(parent_file.parent, repair['parentRequestSha256'])
    expected, changes = _plan(request, original)
    actual = {key: value for key, value in request['revision'].items() if key != 'windowDonors'}
    require(actual == expected and changes == repair.get('dependency')
            and repair.get('parentPlanIdentity') == original['revision']['identity'],
            'section repair plan or dependency closure changed')
    return original


def compatible_donor(request: dict, phase: str) -> tuple[dict, dict]:
    """Revalidate the complete scoped relation immediately before consuming a saved window."""
    original = validate_repair(request)
    expected = request['revision']
    from studio.native_segments.owners import segment_phase
    index = segment_phase(phase)
    require(index is not None and index < len(expected['renderWindows']), 'invalid repaired window phase')
    window = expected['renderWindows'][index]
    require(index < len(original['revision']['renderWindows'])
            and window == original['revision']['renderWindows'][index], 'changed section cannot reuse prior picture')
    file = _seal(original, phase)
    require(file is not None and request['revision'].get('windowDonors', {}).get(phase) == str(file),
            'repair donor is not the admitted parent section')
    record, pins = read_stage(file, bound_json(file)['inputs'], phase)
    require(all(request['pins'].get(path) == sha for path, sha in pins.items()), 'repair donor is unpinned')
    receipt = record['artifacts']['receipt']
    value = bound_json(Path(receipt['path']), receipt['sha256'])
    require(value.get('window') == window and value.get('planIdentity') == original['revision']['identity'],
            'repair donor receipt belongs to another generation')
    return record, value


def reuse_window(request: dict, phase: str, directory: Path) -> dict:
    """Copy original proved picture/probes under the new owner; caller regenerates current PCM."""
    from studio.native_short_picture_reuse import copy_picture
    from studio.native_segments.owners import segment_phase
    if request.get('sectionIntegrations'):
        from studio.native_long_integration import compatible_integration_donor
        record, original = compatible_integration_donor(request, phase)
    else:
        record, original = compatible_donor(request, phase)
    directory.mkdir()
    moved = {}
    for name, row in record['artifacts'].items():
        if name in ('receipt', 'audio') or name.startswith('retainedFrame'):
            continue
        target = directory / f"{name}{Path(row['path']).suffix}"
        copy_picture(Path(row['path']), target, row['sha256'])
        moved[row['path']] = str(target)
    value = {**original, 'planIdentity': request['revision']['identity'],
             'window': request['revision']['renderWindows'][segment_phase(phase)],
             'piece': {**original['piece'], 'path': moved[original['piece']['path']], 'origin': 'reused'},
             'probes': [{**row, 'path': moved[row['path']]} for row in original['probes']],
             'restoredFrom': request['revision']['windowDonors'][phase], 'humanApproved': False}
    value.pop('audio', None)
    from studio.native_segments.frame_capture import relay_frame_capture
    return relay_frame_capture(record, value, request['revision']['windowDonors'][phase])


def section_snapshot_compatibility(original: dict, current: dict, frame_range: list[int]) -> dict:
    """Prove unchanged supported static section inputs across fully pinned immutable snapshots.

    This verifies structural dependency equality, not runtime qualification or
    editorial approval. Callers still validate actual window picture/PCM hashes,
    current authors, independent review and original StageEvidence separately.
    """
    from studio.native_segments.section_closure import section_input_closure
    require(original.get('adapter') == current.get('adapter') == 'native-long', 'snapshot proof requires Long requests')
    require(all(original[key] == current[key] for key in ('runtime', 'tools')),
            'section snapshot runtime or tools changed')
    implementation = _implementation(original)
    require(implementation == _implementation(current), 'section snapshot implementation changed')
    verify_pins(original['pins'])
    verify_pins(current['pins'])
    before = section_input_closure(_project(original), frame_range)
    after = section_input_closure(_project(current), frame_range)
    required = {**before['requiredImplementationPins'], **after['requiredImplementationPins']}
    require(all(implementation.get(file) == sha for file, sha in required.items()),
            'section snapshot compiler or vendored runtime is not pinned')
    require(before['canvas'] == after['canvas'] and before['sharedIdentity'] == after['sharedIdentity']
            and before['sectionIdentity'] == after['sectionIdentity'], 'section snapshot dependencies changed')
    return {'schemaVersion': 1, 'scope': 'unchanged-static-section-inputs-not-runtime-or-editorial-approval',
            'frameRange': list(frame_range), 'rule': before['rule'], 'sharedIdentity': before['sharedIdentity'],
            'sectionIdentity': before['sectionIdentity'], 'implementationIdentity': identity(implementation),
            'originalInputs': identity(original['pins']), 'currentInputs': identity(current['pins']),
            'runtimeQualification': 'not-established'}
