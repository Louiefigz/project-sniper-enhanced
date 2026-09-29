"""Read-only operational eligibility checks over existing immutable window proofs.

A rate miss is data, never a media failure or a request to delete/re-encode it.
Corrupt source evidence still raises through the existing current-window reader.
No ffprobe, child process, hashing shortcut or editorial approval is added here.
"""
from __future__ import annotations

from pathlib import Path
from fractions import Fraction
from math import ceil

from cut_preview_io import bound_json
from native_work_service_pins import identity, require
from native_work_service_schema import BOUND_DIMENSIONS, validate_contract


def regular_size(file: Path) -> int:
    """Stat a canonical regular file without reading media bytes."""
    require(file.is_absolute() and file.resolve(strict=True) == file and not file.is_symlink()
            and file.is_file(), 'service input is not a canonical regular file')
    return file.stat().st_size


def candidate_files(request: dict, scope: dict) -> tuple[list[dict], dict, list[Path]]:
    """Read bounded candidate metadata for size screening; this grants no seal validity."""
    root = Path(request['output'])
    values = [bound_json(root / f"segment-picture-{row['index']}.json") for row in scope['windows']]
    prepared_file = root / 'prepared-audio.json'
    prepared = bound_json(prepared_file)
    master = bound_json(Path(prepared['masterReceipt']))
    files = [Path(name) for name in request['pins']]
    files += [root / 'export-request.json', prepared_file, Path(prepared['masterReceipt']),
              Path(master['output']), Path(prepared['reference'])]
    for value in values:
        files.extend((Path(value['piece']['path']), Path(value['audio']['path'])))
        phase = f"segment-picture-{value['window']['index']}"
        direct = root / f'{phase}-stage.json'
        files.append(direct if direct.exists() else Path(request['revision']['windowDonors'][phase]))
    return values, {'master': master, 'prepared': prepared}, sorted(set(files))


def dimensions(scope: dict, values: list[dict], audio: dict, files: list[Path]) -> dict:
    """Record bytes and a coarse one-frame bitrate upper bound, never an observed peak.

    No frame packet can exceed its complete window file. The calibration uses
    this identical predictor: ceil(max(window file bytes) * 8 * exact fps).
    """
    sizes = [regular_size(Path(row['piece']['path'])) for row in values]
    rate = Fraction(scope['frameRate'])
    return {'frames': scope['frameRange'][1] - scope['frameRange'][0], 'windows': len(values),
            'pictureBytes': sum(sizes),
            'masterBytes': regular_size(Path(audio['master']['output'])),
            'referenceBytes': regular_size(Path(audio['prepared']['reference'])),
            'pinnedInputBytes': sum(regular_size(file) for file in files), 'proofFiles': len(files),
            'peakBitrate': ceil(max(sizes) * 8 * rate)}


def bounds_misses(facts: dict, selection: dict) -> list[str]:
    """Unknown observed facts and exceeded eligibility bounds cannot retain a faster rate."""
    limits = selection['bounds']
    misses = [f'{key}:unobserved' if facts[key] is None else f'{key}:outside-envelope'
              for name, key in BOUND_DIMENSIONS.items() if facts[key] is None or facts[key] > limits[name]]
    if facts['frames'] < limits['minFrames']:
        misses.append('frames:below-exercised-minimum')
    return misses


def stream_misses(request: dict, values: list[dict], audio: dict, conditions: dict) -> list[str]:
    """Compare the actual sealed encoder/stream and mastered format with the proposed rate contract."""
    misses = []
    for row in values:
        if row.get('encoder', {}).get('contractSha256') != conditions['encoderContractSha256']:
            misses.append('encoder:changed-or-unobserved')
        stream = row['piece'].get('stream', {})
        same = all(stream.get(key) == conditions['canvas'][key] for key in ('width', 'height'))
        if not same or Fraction(stream.get('r_frame_rate', '0')) != Fraction(conditions['canvas']['frameRate']):
            misses.append('stream:geometry-or-clock-changed')
    clock = audio['master'].get('masterClock', {})
    audio_format = {key: clock.get(key) for key in ('sampleRate', 'channels')}
    audio_format['sampleFormat'] = clock.get('codec')
    if clock.get('sampleFormat') != 'flt' or audio_format != conditions['audio']:
        misses.append('audio:changed-or-unobserved')
    if request.get('adapter') != 'native-long':
        misses.append('format:not-long')
    return sorted(set(misses))


def actual_service(request: dict, scope_id: str, evidence: dict, conditions: dict | None = None) -> dict:
    """Screen sizes before hashing, then preserve every valid seal despite an operational miss.

    The current owner supplies freshly admitted runtime/filesystem conditions.
    peakBitrate is an exercised conservative file-size predictor, not an observed
    stream bitrate. It cannot manufacture media validity or permit decoding.
    """
    from studio.native_segments.review_media import source_state
    from studio.native_segments.review_scopes import request_scope
    require(evidence['identity'] == identity({key: value for key, value in evidence.items() if key != 'identity'}),
            'frozen service evidence changed')
    scope = request_scope(request, scope_id)
    selected = next(row['selection'] for row in evidence['envelopes']
                    if row['scopeId'] == scope_id and row['site'] == 'package-create')
    values, audio, files = candidate_files(request, scope)
    facts = dimensions({**scope, 'frameRate': request['revision']['canvas']['frameRate']}, values, audio, files)
    misses = bounds_misses(facts, selected) if selected else ['no-frozen-service-cell']
    exceeded = [reason for reason in misses if reason.endswith('outside-envelope')]
    if exceeded:
        return {'status': 'miss', 'reasons': misses, 'facts': facts, 'mediaValidated': False}
    _signature, validated, _prepared = source_state(request, scope)
    require(values == validated, 'service metadata changed during cold source validation')
    if conditions is None:
        misses.append('current-runtime-filesystem-conditions:unobserved')
    else:
        validate_contract(conditions)
        if conditions != evidence['conditions']:
            misses.append('current-service-conditions:changed')
        misses.extend(stream_misses(request, validated, audio, conditions))
    return {'status': 'miss' if misses else 'eligible', 'reasons': sorted(set(misses)),
            'facts': facts, 'mediaValidated': True}
