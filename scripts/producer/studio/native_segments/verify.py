"""Technical proofs for an assembled revision picture. Nothing here grants editorial approval.

- Assembly: exact frame count, one constant clock, the delivered stream contract, and every
  piece's packet payloads unchanged (copied GOPs bit-exact to the delivered picture, rendered
  windows bit-exact to their sealed segments).
- Dependency probes: frames captured from the revised project inside reused GOPs must match the
  delivered frames within an encoding tolerance measured per 16x16 block, so a change the
  structural closure missed is refused instead of shipped as stale picture.
- Context tolerance: re-rendered frames outside the semantic edit bounds must stay within an
  encoding tolerance of the delivered frames; they are never claimed bit-exact.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image

from cut_preview_io import read_bytes
from studio.native_segments.manifest import Tools, check_clock, packet_table, payload_digest, run_tool, stream_contract
from studio.native_selected_frames import MAX_FRAME_BYTES, SelectedFrames, compare_selected_frames, selection_expression
from studio.native_stage_evidence import require

BLOCK = 16
# JPEG q95 capture vs x264 crf15 decode of unchanged content measured worst-block 5.3-6.4 and 41.8-44.2 dB
# (Q1, 8 probes); real changed frames measured worst-block 124-225 and 17-25 dB (F1 phase 3 finding).
PROBE_LIMITS = {'psnrMinimumDb': 35.0, 'blockMaeMaximum': 12.0}
CONTEXT_PSNR_MINIMUM_DB = 40.0


def verify_assembly(output: Path, pieces: list[dict], tools: Tools, reference: dict) -> dict:
    """Frame count, clock, stream contract and per-piece payload identity of the assembled picture."""
    packets = packet_table(output, tools)
    tick = check_clock(packets, pieces[-1]['endFrameExclusive'])
    require(stream_contract(output, tools) == reference, 'assembled stream parameters differ from the delivered picture')
    for row in pieces:
        part = packets[row['startFrame']:row['endFrameExclusive']]
        require(part[0]['key'] and payload_digest(part) == row['packets']['payloadSha256'],
                f"piece [{row['startFrame']},{row['endFrameExclusive']}) payload changed during assembly")
    return {'packets': len(packets), 'tick': tick, 'piecePayloadsIdentical': True,
            'keyframes': [index for index, row in enumerate(packets) if row['key']]}


def payloads_match(file: Path, pieces: list[dict], tools: Tools) -> bool:
    """Per-piece packet payloads survive a later container write (audio mux, color metadata)."""
    packets = packet_table(file, tools)
    return len(packets) == pieces[-1]['endFrameExclusive'] and all(
        payload_digest(packets[row['startFrame']:row['endFrameExclusive']]) == row['packets']['payloadSha256']
        for row in pieces)


def block_metrics(reference: np.ndarray, actual: np.ndarray) -> dict:
    """Whole-frame MAE/PSNR and the worst 16x16 block mean absolute difference."""
    require(reference.shape == actual.shape and reference.ndim == 3, 'probe and delivered frame geometry differ')
    delta = np.abs(reference.astype(np.float64) - actual.astype(np.float64))
    mse = float(np.mean(delta * delta))
    rows, columns = np.arange(0, delta.shape[0], BLOCK), np.arange(0, delta.shape[1], BLOCK)
    sums = np.add.reduceat(np.add.reduceat(delta.sum(axis=2), rows, axis=0), columns, axis=1)
    heights = np.diff(np.append(rows, delta.shape[0]))[:, None]
    widths = np.diff(np.append(columns, delta.shape[1]))[None, :]
    blocks = sums / (heights * widths * 3)  # edge blocks are partial, never dropped
    worst = np.unravel_index(int(np.argmax(blocks)), blocks.shape)
    return {'mae': float(np.mean(delta)), 'psnrDb': float(10 * math.log10(255 * 255 / mse)) if mse else 100.0,
            'blockMaeMaximum': float(blocks.max()), 'worstBlock': [int(worst[1]) * BLOCK, int(worst[0]) * BLOCK]}


def probe_verdict(metrics: dict) -> bool:
    """Within the capture-versus-encode tolerance everywhere in the frame."""
    return (metrics['psnrDb'] >= PROBE_LIMITS['psnrMinimumDb']
            and metrics['blockMaeMaximum'] <= PROBE_LIMITS['blockMaeMaximum'])


def verify_probes(probes: list[dict], delivered: Path, total_frames: int, directory: Path) -> dict:
    """Revised-project captures inside reused GOPs against the delivered frames; any miss refuses."""
    if not probes:
        return {'probes': 0, 'passed': True, 'limits': PROBE_LIMITS}
    selection = SelectedFrames(tuple(row['frame'] for row in probes), 1080, 1920, total_frames)
    return compare_probes(probes, delivered, selection, directory)


def verify_long_probes(probes: list[dict], delivered: Path, canvas: dict, directory: Path) -> dict:
    """Compare admitted Long geometry without treating Short tolerances as Long qualification."""
    require(bool(probes), 'Long dependency comparison needs actual current-project probes')
    selection = SelectedFrames(tuple(row['frame'] for row in probes), canvas['width'], canvas['height'], canvas['totalFrames'])
    result = compare_probes(probes, delivered, selection, directory)
    return {**result, 'canvas': dict(canvas), 'runtimeQualification': 'not-established',
            'limitsBasis': 'Short diagnostic limits only; actual Long runtime qualification required'}


class SegmentSelectedFrames(SelectedFrames):
    """Interpret native segment samples using the final route's exact sRGB metadata correction."""

    @property
    def filter_bytes(self) -> bytes:
        """Change input color interpretation only; do not encode or mutate the donor bitstream."""
        return (b'setparams=range=limited:color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709,'
                + super().filter_bytes)


def verify_long_segment_probes(probes: list[dict], piece: dict, canvas: dict, directory: Path) -> dict:
    """Compare current absolute captures against matching zero-based donor segment frames."""
    from studio.native_segments.manifest import FINAL_COLOR
    require(bool(probes) and all(piece['stream'].get(key) == value for key, value in FINAL_COLOR.items()),
            'unexpected native segment probe color route')
    start, end = piece['startFrame'], piece['endFrameExclusive']
    local = [{**row, 'frame': row['frame'] - start} for row in probes]
    selection = SegmentSelectedFrames(tuple(row['frame'] for row in local), canvas['width'], canvas['height'], end - start)
    result = compare_probes(local, Path(piece['path']), selection, directory)
    return {**result, 'absoluteFrames': [row['frame'] for row in probes], 'canvas': canvas,
            'colorInterpretation': 'existing-native-final-srgb-metadata-correction', 'runtimeQualification': 'not-established',
            'scope': 'this-current-project-versus-donor-sample-comparison-only'}


def compare_probes(probes: list[dict], delivered: Path, selection: SelectedFrames, directory: Path) -> dict:
    """Decode the exact admitted canvas and compare every pinned current capture once."""
    by_frame = {row['frame']: row for row in probes}
    require(len(by_frame) == len(probes), 'duplicate dependency probe frame')

    def compare(frame: int, pixels: np.ndarray) -> dict:
        """One probe against its delivered frame."""
        raw = read_bytes(Path(by_frame[frame]['path']), maximum=MAX_FRAME_BYTES)
        import hashlib
        require(hashlib.sha256(raw).hexdigest() == by_frame[frame]['sha256'], 'dependency probe bytes changed')
        with Image.open(io.BytesIO(raw)) as image:
            captured = np.asarray(image.convert('RGB'))
        metrics = block_metrics(captured, pixels)
        return {'frame': frame, **metrics, 'passed': probe_verdict(metrics)}
    directory.mkdir()
    rows, decoded = compare_selected_frames(delivered, selection, compare, directory)
    failed = [row for row in rows if not row['passed']]
    require(not failed, f"dependency probe found a changed frame outside the planned closure at frame "
            f"{failed[0]['frame'] if failed else None}; the structural plan missed a dependency, nothing is reused")
    return {'probes': len(rows), 'passed': True, 'limits': PROBE_LIMITS, 'rows': rows, 'decode': decoded}


def context_frames(windows: list[dict], semantic: list[list[int]]) -> list[int]:
    """Re-rendered frames outside the semantic edit bounds."""
    return [frame for row in windows for frame in range(row['startFrame'], row['endFrame'])
            if not any(start <= frame < end for start, end in semantic)]


def frame_psnr(left: Path, right: Path, frames: list[int], tools: Tools) -> list[float]:
    """Per-frame average PSNR of two pictures over the selected frame indexes."""
    select = selection_expression(tuple(frames))
    graph = (f"[0:v]select='{select}',setpts=N/TB,format=yuv420p[a];"
             f"[1:v]select='{select}',setpts=N/TB,format=yuv420p[b];[a][b]psnr=stats_file=-")
    text = run_tool([tools.ffmpeg, '-nostdin', '-v', 'error', '-i', str(left), '-i', str(right),
                     '-filter_complex', graph, '-f', 'null', '-'], timeout=900).decode()
    values = []
    for line in text.splitlines():
        fields = dict(token.split(':', 1) for token in line.split() if ':' in token)
        if 'psnr_avg' in fields:
            values.append(math.inf if fields['psnr_avg'] == 'inf' else float(fields['psnr_avg']))
    require(len(values) == len(frames), 'context comparison decoded an incomplete frame inventory')
    return values


def verify_context(assembled: Path, delivered: Path, frames: list[int], tools: Tools) -> dict:
    """Re-rendered context frames stay within the encoding tolerance of the delivered picture."""
    if not frames:
        return {'frames': 0, 'passed': True}
    values = frame_psnr(assembled, delivered, frames, tools)
    finite = [value for value in values if math.isfinite(value)]
    worst = min(finite) if finite else None
    require(worst is None or worst >= CONTEXT_PSNR_MINIMUM_DB,
            f're-rendered context frame differs beyond tolerance ({worst} dB)')
    return {'frames': len(frames), 'identicalFrames': len(values) - len(finite), 'minimumPsnrDb': worst,
            'meanPsnrDb': sum(finite) / len(finite) if finite else None,
            'minimumAllowedDb': CONTEXT_PSNR_MINIMUM_DB, 'passed': True, 'bitExactClaimed': False}
