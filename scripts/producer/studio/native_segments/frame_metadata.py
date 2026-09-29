"""Necessary metadata-size admission for retained Long frames under existing JSON limits.

This checks structural lower bounds, not a promise about dynamic telemetry size.
It never raises the shared reader ceiling or claims render/resource qualification.
"""
from __future__ import annotations

from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import MAX_JSON
from studio.native_stage_evidence import require

DIGEST_PLACEHOLDER = '0' * 64


def future_frame_pins(request: dict, evidence: dict) -> dict[str, str]:
    """Account for the complete successful JPEG inventory later accumulated by assembly."""
    from studio.native_long_scope import selected_windows
    from studio.native_segments.worker import MAX_TRIES
    root, pins = Path(request['output']), {}
    donors = request['revision'].get('windowDonors', {})
    for window in selected_windows(request):
        phase = f"segment-picture-{window['index']}"
        if phase in donors:
            continue  # Original donor JPEGs already belong to the admitted input closure.
        directories = [root / f"segment-{window['index']:03d}-try-{attempt}" for attempt in range(MAX_TRIES)]
        directory = next((candidate for candidate in directories
                          if str(candidate / 'retained-frames.json') in evidence), directories[-1])
        pins.update({str(directory / 'frames' / f'frame_{frame:06d}.jpg'): DIGEST_PLACEHOLDER
                     for frame in range(window['startFrame'], window['endFrame'])})
        owner = next((root / f'{label}.render.json' for label in (phase, phase + '-retry-1')
                      if str(root / f'{label}.render.json') in evidence), root / f'{phase}-retry-1.render.json')
        paths = [root / f'{phase}.json', root / f'{phase}-stage.json', owner,
                 directory / 'retained-frames.json', directory / 'picture.mp4', directory / 'section-audio.wav']
        if phase in request.get('sectionFrameReuse', {}):
            paths.append(directory / 'retained-frame-proof.json')
        pins.update({str(file): DIGEST_PLACEHOLDER for file in paths})
    return pins


def metadata_lower_bounds(request: dict, evidence: dict, context: tuple[dict, dict]) -> dict[str, int]:
    """Size necessary known owner fields, keeping this projection separate from completed evidence."""
    owner_pins, sources = context
    future = future_frame_pins(request, {**request['pins'], **evidence})
    pins = {**owner_pins, **request['pins'], **evidence, **future,
            str(Path(request['output']) / 'export-request.json'): DIGEST_PLACEHOLDER}
    owner = {'additionalFilePinsBefore': pins, 'additionalFilePinsAfter': pins,
             'sourceHashesBefore': sources, 'sourceHashesAfter': sources}
    stage = {'inputs': request['pins'], 'supervisorPins': pins}
    return {name: len(canonical_compact_json(value).encode()) + 1
            for name, value in (('request', request), ('futureOwner', owner), ('futureStage', stage))}


def require_retained_metadata_capacity(request: dict, evidence: dict | None = None) -> None:
    """Refuse structurally impossible receipts before media; dynamic receipt bounds still apply."""
    if request.get('revision', {}).get('mode') != 'initial-long':
        return
    from studio.native_run_config import owner_file_pins, source_hashes
    sizes = metadata_lower_bounds(request, evidence or {},
                                  (owner_file_pins(), source_hashes(Path(request['project']))))
    require(all(size <= MAX_JSON for size in sizes.values()),
            'retained Long metadata necessarily exceeds existing JSON bound before media: ' + str(sizes))
