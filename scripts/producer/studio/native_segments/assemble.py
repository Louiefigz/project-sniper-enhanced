"""Build a revision's picture.mp4 inside its draft or final media owner, never encoding picture.

- ``picture-reuse``: the picture inputs are unchanged, so the delivered picture is copied exactly.
- ``segments``: the delivered picture is split at its closed GOPs by packet copy, each reused GOP is
  proved bit-exact to the delivered packets, the sealed windows take their places, and the pieces
  are concatenated with ``-auto_convert 0`` (the concat demuxer's default conversion would insert
  in-band SPS/PPS into every keyframe and silently change "copied" payloads). Payloads, clock,
  dependency probes and re-rendered context frames are proved before audio.
- ``full-render``: every window of the new timeline was rendered; they are concatenated the same way
  (nothing is copied from the delivered picture).
Incompatible streams are refused; nothing is re-encoded to hide a mismatch.
"""
from __future__ import annotations

import time
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_runtime import digest
from studio.native_segments.manifest import (
    Tools, check_bytes, check_compatible, check_coverage, describe_piece, run_tool,
)
from studio.native_segments.owners import current_window, revision_windows, segment_output
from studio.native_segments.verify import context_frames, verify_assembly, verify_context, verify_probes
from studio.native_stage_evidence import require

RECEIPT = 'revision-picture.json'


def split_delivered(revision: dict, directory: Path, tools: Tools) -> dict[int, dict]:
    """Packet-copy the delivered picture into its GOPs; prove each reused one bit-exact."""
    picture, grid = Path(revision['ancestor']['picture']['path']), revision['grid']
    require(digest(picture) == revision['ancestor']['picture']['sha256'], 'delivered picture changed before reuse')
    directory.mkdir()
    starts = ','.join(str(start) for start, _end in grid['gops'][1:])
    split = ['-f', 'segment', '-segment_frames', starts] if starts else ['-f', 'segment', '-segment_time', '100000']
    run_tool([tools.ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(picture), '-map', '0:v:0', '-c', 'copy',
              *split, '-reset_timestamps', '1', '-segment_format', 'mp4',
              '-segment_format_options', f"video_track_timescale={grid['timescale']}", str(directory / 'gop-%03d.mp4')])
    pieces = {}
    for index in revision['reusedGops']:
        start, end = grid['gops'][index]
        piece = describe_piece(directory / f'gop-{index:03d}.mp4', (start, end), tools)
        require(piece['packets']['payloadSha256'] == grid['payloads'][index],
                f'copied GOP {index} differs from the delivered picture packets')
        pieces[index] = {**piece, 'origin': 'delivered', 'gop': index}
    return pieces


def concat(pieces: list[dict], output: Path, tools: Tools, timescale: int) -> None:
    """Stream-copy the ordered pieces into one picture (absolute, unambiguous paths only)."""
    lines = ['ffconcat version 1.0']
    for row in pieces:
        require(row['path'].startswith('/') and not any(char in row['path'] for char in "'\n\r\\"),
                'unsafe piece path')
        lines.append(f"file '{row['path']}'")
    listing = output.parent / 'revision-pieces.ffconcat'
    listing.write_text('\n'.join(lines) + '\n')
    run_tool([tools.ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-auto_convert', '0', '-f', 'concat', '-safe', '0',
              '-i', str(listing), '-map', '0:v:0', '-c', 'copy', '-video_track_timescale', str(timescale),
              '-n', str(output)])


def ordered_pieces(request: dict, delivered: dict[int, dict]) -> list[dict]:
    """Delivered GOPs and sealed windows in timeline order, each exactly once."""
    revision = request['revision']
    windows = {row['gop']: current_window(request, f"segment-picture-{row['index']}")['piece']
               for row in revision['renderWindows']}
    require(set(windows).isdisjoint(delivered) and len(windows) + len(delivered) == len(revision['grid']['gops']),
            'windows and reused GOPs do not partition the delivered grid')
    return [windows.get(index) or delivered[index] for index in range(len(revision['grid']['gops']))]


def assemble_segments(request: dict, root: Path, tools: Tools) -> dict:
    """Split, prove, concatenate and verify; returns the picture section of the receipt."""
    revision, started = request['revision'], time.monotonic()
    delivered = split_delivered(revision, root / 'revision-pieces', tools) if revision['reusedGops'] else {}
    pieces = ordered_pieces(request, delivered)
    reference = revision['grid']['stream'] or pieces[0]['stream']
    check_coverage(pieces, revision['grid']['gops'][-1][1])
    check_compatible(pieces, reference)
    check_bytes(pieces)
    concat(pieces, root / 'picture.mp4', tools, revision['grid']['timescale'])
    check_bytes(pieces)
    assembly = verify_assembly(root / 'picture.mp4', pieces, tools, reference)
    assembled = time.monotonic()
    video = Path(revision['ancestor']['video']['path'])
    first = current_window(request, 'segment-picture-0')
    probes = verify_probes(first['probes'], video, pieces[-1]['endFrameExclusive'], root / 'revision-probes')
    frames = context_frames(revision['renderWindows'], revision['dependency']['semanticBounds'])
    context = verify_context(root / 'picture.mp4', Path(revision['ancestor']['picture']['path']), frames, tools)
    return {'pieces': [{key: row[key] for key in ('startFrame', 'endFrameExclusive', 'origin', 'sha256')}
                       for row in pieces], 'assembly': assembly, 'dependencyProbes': probes, 'context': context,
            'framesCopied': sum(row['frames'] for row in pieces if row['origin'] == 'delivered'),
            'framesRendered': sum(row['frames'] for row in pieces if row['origin'] == 'rendered'),
            'seconds': {'assemble': assembled - started, 'verify': time.monotonic() - assembled}}


def assemble_initial(request: dict, root: Path, tools: Tools) -> dict:
    """Join all reviewed current Long sections, then recheck before atomic publication."""
    from studio.native_segments.reviews import assembly_snapshot
    frozen = assembly_snapshot(request)
    pieces = ordered_pieces(request, {})
    reference = pieces[0]['stream']
    check_coverage(pieces, request['revision']['grid']['gops'][-1][1])
    check_compatible(pieces, reference)
    check_bytes(pieces)
    pending = root / 'picture.pending.mp4'
    concat(pieces, pending, tools, request['revision']['grid']['timescale'])
    check_bytes(pieces)
    assembly = verify_assembly(pending, pieces, tools, reference)
    from studio.production.section_publication import recheck_publication, section_publication
    with section_publication(request) as production_record:
        require(assembly_snapshot(request, production_record) == frozen,
                'section generation or QC changed during assembly')
        require(not (root / 'picture.mp4').exists(), 'picture publication already exists')
        recheck_publication(request, production_record)
        pending.rename(root / 'picture.mp4')
    donors = request['revision'].get('windowDonors', {})
    reused = sum(row['endFrame'] - row['startFrame'] for row in revision_windows(request)
                 if f"segment-picture-{row['index']}" in donors)
    return {'pieces': pieces, 'assembly': assembly, 'sectionSnapshot': frozen,
            'framesCopied': reused, 'framesRendered': sum(row['frames'] for row in pieces) - reused,
            'finalQcRequired': True}


def window_encodes(request: dict) -> int:
    """Picture encodes this attempt ran: its window owners' encodes (restored windows were encoded before)."""
    root = Path(request['output'])
    return sum(1 for window in revision_windows(request)
               if 'restoredFrom' not in bound_json(root / segment_output(f"segment-picture-{window['index']}")))


def revision_picture(request: dict) -> dict | None:
    """Produce picture.mp4 for a revision (exact reuse or window assembly); None for any other request."""
    revision = request.get('revision')
    if not revision:
        return None
    from studio.native_short_picture_reuse import copy_picture
    root, tools = Path(request['output']), Tools.of(request)
    if revision['mode'] == 'picture-reuse':
        started = time.monotonic()
        picture = revision['ancestor']['picture']
        copy_picture(Path(picture['path']), root / 'picture.mp4', picture['sha256'])
        section = {'framesCopied': revision['cost']['framesReused'], 'framesRendered': 0,
                   'exactWholePicture': True, 'seconds': {'copy': time.monotonic() - started}}
    elif revision['mode'] == 'initial-long':
        section = assemble_initial(request, root, tools)
    else:
        section = assemble_segments(request, root, tools)
    receipt = {'schemaVersion': 1, 'mode': revision['mode'], 'planIdentity': revision['identity'],
               'sha256': digest(root / 'picture.mp4'), 'pictureEncodesHere': 0, 'windowEncodes': window_encodes(request),
               **section, 'humanApproved': False}
    write_new(root / RECEIPT, receipt)
    return receipt
