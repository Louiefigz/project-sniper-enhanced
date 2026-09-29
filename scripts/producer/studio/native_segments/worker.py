"""Window owner worker: render one admitted window, then prove it before publishing its receipt.

Runs as ``native_short_worker.py <request> segment-picture-<i>`` under its live export owner.
The Node child renders the absolute-frame window through the existing capture primitive and
batch encoder (studio/native_segments/render.mjs). This side then proves the segment opens with
an IDR, keeps a zero-based constant clock, and is packet-compatible with the delivered picture
it will replace a GOP of, before any later window or assembly starts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_runtime import digest
from studio.native_segments.manifest import Tools, check_compatible, describe_piece
from studio.native_segments.owners import revision_windows, segment_output, segment_phase
from studio.native_stage_evidence import require

RENDER = Path(__file__).with_name('render.mjs')
WINDOW_SECONDS = 570  # inside the owner's 600-second work limit, clamped by any production allocation
MAX_TRIES = 8


def try_directory(root: Path, index: int) -> Path:
    """A fresh capture directory for this owner (a retried window never reuses a failed one's files)."""
    for attempt in range(MAX_TRIES):
        candidate = root / f'segment-{index:03d}-try-{attempt}'
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise RuntimeError('segment window exceeded its try-directory bound')


def verify_probes(probes: list[dict], expected: list[int]) -> None:
    """Every requested dependency probe was captured once, in order, with intact bytes."""
    require([row['frame'] for row in probes] == expected, 'dependency probe inventory differs from the plan')
    for row in probes:
        require(digest(Path(row['path'])) == row['sha256'], f"dependency probe {row['frame']} changed")


def execute_segment(request: dict, phase: str) -> dict:
    """Render one window, describe and check its segment, and publish the owner's receipt."""
    index, revision = segment_phase(phase), request['revision']
    windows = revision_windows(request)
    require(index is not None and index < len(windows), 'segment phase is outside the revision plan')
    window, root = windows[index], Path(request['output'])
    directory = try_directory(root, index)
    if (request.get('sectionRepair') or request.get('sectionIntegrations')) and phase in revision.get('windowDonors', {}):
        return reuse_section(request, phase, directory)
    from studio.native_segments.frame_capture import require_frame_reuse, finish_frame_capture
    require_frame_reuse(request, phase)
    command = [request['tools']['node'], str(RENDER), str(root / 'export-request.json'), str(index), str(directory)]
    subprocess.run(command, check=True, timeout=WINDOW_SECONDS)
    receipt = bound_json(directory / 'window.json')
    require(receipt.get('window') == window and receipt.get('planIdentity') == revision['identity'],
            'segment child rendered another window or plan')
    piece = describe_piece(Path(receipt['path']), (window['startFrame'], window['endFrame']), Tools.of(request))
    require(piece['sha256'] == receipt['sha256'] and len(receipt['frameSha256']) == piece['frames'],
            'segment bytes or frame inventory differ from the child receipt')
    check_compatible([piece], revision['grid']['stream'] or piece['stream'])  # full render: checked at assembly
    verify_probes(receipt['probes'], revision['probes'] if index == 0 else [])
    audio = section_audio(request, window, directory) if revision['mode'] == 'initial-long' else None
    result = {'schemaVersion': 1, 'phase': phase, 'planIdentity': revision['identity'], 'window': window,
              'piece': {**piece, 'origin': 'rendered'}, 'frameSha256': receipt['frameSha256'],
              'probes': receipt['probes'], 'encoder': receipt['encoder'], 'sessions': receipt['sessions'],
              'timings': receipt['timings'], 'sourceCache': receipt.get('sourceCache'),
              'humanApproved': False}
    result.update(finish_frame_capture(request, phase, receipt))
    if audio:
        result['audio'] = audio
    write_new(root / segment_output(phase), result)
    return result


def section_audio(request: dict, window: dict, directory: Path) -> dict:
    """Keep exact full-master PCM beside each picture so independent listening can bind its clock."""
    from studio.native_long_worker import read_long_audio
    from studio.native_motion_previews import audio_excerpt
    return audio_excerpt(request, read_long_audio(request),
                         {**window, 'canvas': request['revision']['canvas']}, directory / 'section-audio.wav')


def reuse_section(request: dict, phase: str, directory: Path) -> dict:
    """Keep proved picture bytes while producing fresh current audio under this owner."""
    from studio.native_segments.compatibility import reuse_window
    from studio.native_segments.probe import execute_dependency_probe
    value = reuse_window(request, phase, directory)
    value['dependencyProbe'] = execute_dependency_probe(request, phase, directory, value)
    value['audio'] = section_audio(request, value['window'], directory)
    write_new(Path(request['output']) / segment_output(phase), value)
    return value
