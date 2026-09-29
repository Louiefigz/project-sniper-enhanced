"""Final-picture pieces: exact stream, packet and random-access evidence for stream-copy assembly.

A piece is one contiguous half-open frame range held in its own MP4: either a window this
revision rendered, or a closed GOP copied out of the delivered ancestor picture. Assembly
concatenates pieces by packet copy only, so every piece must share the stream parameters that
decoders read (codec, profile, level, geometry, color tags, clock and the exact SPS/PPS
extradata), open with an IDR access unit, and carry a zero-based constant clock without
reordering. The evidence is technical only; it grants no editorial or delivery authority.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from studio.native_runtime import digest
from studio.native_stage_evidence import require

STREAM_KEYS = ('codec_name', 'profile', 'level', 'pix_fmt', 'width', 'height', 'color_range',
               'color_space', 'color_transfer', 'color_primaries', 'r_frame_rate', 'time_base',
               'has_b_frames', 'extradata_hash')
FINAL_COLOR = {'color_range': 'tv', 'color_space': 'bt709', 'color_transfer': 'bt709', 'color_primaries': 'bt709'}
IDR_NAL = 5
NAL_LENGTH_BYTES = 4
MAX_PIECES = 768


@dataclass(frozen=True)
class Tools:
    """Admitted FFmpeg and ffprobe executables (the request's pinned tools)."""

    ffmpeg: str
    ffprobe: str

    @classmethod
    def of(cls, request: dict) -> 'Tools':
        """The tools an export request pinned."""
        return cls(request['tools']['ffmpeg'], request['tools']['ffprobe'])


def run_tool(args: list[str], timeout: float = 600) -> bytes:
    """Run one bounded local media command and return its standard output."""
    return subprocess.run(args, capture_output=True, check=True, timeout=timeout).stdout


def stream_contract(file: Path, tools: Tools) -> dict:
    """The picture stream parameters that packet-copy concatenation requires to match."""
    data = json.loads(run_tool([tools.ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams',
                                '-show_data_hash', 'sha256', '-of', 'json', str(file)]))
    require(len(data['streams']) == 1, f'expected exactly one picture stream in {file}')
    return {key: data['streams'][0].get(key) for key in STREAM_KEYS}


def packet_table(file: Path, tools: Tools) -> list[dict]:
    """Integer timestamps, keyframe flag, file position, size and payload hash of every picture packet."""
    data = json.loads(run_tool([tools.ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_packets',
                                '-show_data_hash', 'sha256', '-show_entries',
                                'packet=pts,dts,duration,flags,pos,size,data_hash', '-of', 'json', str(file)]))
    return [{'pts': int(row['pts']), 'dts': int(row['dts']), 'duration': int(row['duration']),
             'key': 'K' in row['flags'], 'pos': int(row['pos']), 'size': int(row['size']),
             'hash': row['data_hash']} for row in data['packets']]


def packet_nal_types(file: Path, packet: dict) -> list[int]:
    """NAL unit types of one length-prefixed MP4 sample, read at its recorded file position.

    Code finds WHERE: it walks 4-byte NAL lengths and requires them to consume the sample
    exactly, so a different length size or a damaged sample is refused instead of guessed.
    """
    with file.open('rb') as handle:
        handle.seek(packet['pos'])
        data = handle.read(packet['size'])
    require(len(data) == packet['size'], f'short picture sample read in {file}')
    types, offset = [], 0
    while offset < len(data):
        require(offset + NAL_LENGTH_BYTES < len(data), f'truncated NAL length in {file}')
        length = int.from_bytes(data[offset:offset + NAL_LENGTH_BYTES], 'big')
        start = offset + NAL_LENGTH_BYTES
        require(0 < length <= len(data) - start, f'NAL lengths do not consume the sample in {file}')
        types.append(data[start] & 0x1F)
        offset = start + length
    return types


def payload_digest(packets: list[dict]) -> str:
    """One digest over ordered packet payload hashes; timestamps are bound separately."""
    return hashlib.sha256('\n'.join(row['hash'] for row in packets).encode()).hexdigest()


def check_clock(packets: list[dict], frames: int) -> int:
    """Require a zero-based, constant-duration, reorder-free packet clock; return its tick."""
    require(len(packets) == frames and frames > 0, 'picture packet count differs from its frame range')
    tick = packets[0]['duration']
    require(tick > 0 and all(row['pts'] == row['dts'] == index * tick and row['duration'] == tick
                             for index, row in enumerate(packets)),
            'picture timestamps are not a zero-based constant-rate sequence without reordering')
    return tick


def idr_keyframes(file: Path, packets: list[dict]) -> list[int]:
    """Indexes of keyframes; every keyframe must be an IDR access unit (closed GOP)."""
    keys = [index for index, row in enumerate(packets) if row['key']]
    require(keys and keys[0] == 0, f'picture does not open with a keyframe: {file}')
    for index in keys:
        require(IDR_NAL in packet_nal_types(file, packets[index]),
                f'keyframe {index} of {file} is not an IDR access unit (open GOP is unsupported)')
    return keys


def describe_piece(file: Path, frames: tuple[int, int], tools: Tools) -> dict:
    """Bind one piece's bytes, stream contract, clock, IDR start and packet payloads."""
    start, end = frames
    packets = packet_table(file, tools)
    tick = check_clock(packets, end - start)
    keys = idr_keyframes(file, packets)
    return {'startFrame': start, 'endFrameExclusive': end, 'frames': end - start, 'path': str(file),
            'sha256': digest(file), 'stream': stream_contract(file, tools),
            'packets': {'count': len(packets), 'tick': tick, 'keyframes': keys,
                        'payloadSha256': payload_digest(packets)}}


def check_compatible(pieces: list[dict], reference: dict) -> None:
    """Every piece shares the reference stream contract (extradata included) and the bt709 tags."""
    require(0 < len(pieces) <= MAX_PIECES, 'invalid picture piece count')
    require({key: reference[key] for key in FINAL_COLOR} == FINAL_COLOR,
            'pieces are not on the final bt709 color contract (preview color must never reach a final)')
    for row in pieces:
        differing = sorted(key for key in STREAM_KEYS if row['stream'][key] != reference[key])
        require(not differing, f"piece [{row['startFrame']},{row['endFrameExclusive']}) is not "
                f'packet-compatible with the delivered picture: {differing}; nothing is re-encoded to hide it')


def check_coverage(pieces: list[dict], total_frames: int) -> None:
    """Ordered, gap-free, overlap-free coverage of the complete canvas."""
    require(bool(pieces) and pieces[0]['startFrame'] == 0 and pieces[-1]['endFrameExclusive'] == total_frames,
            'pieces do not cover the canvas')
    for left, right in zip(pieces, pieces[1:]):
        require(left['endFrameExclusive'] == right['startFrame'], 'piece gap or overlap')


def check_bytes(pieces: list[dict]) -> None:
    """Cold-read every piece against its recorded digest."""
    for row in pieces:
        require(digest(Path(row['path'])) == row['sha256'],
                f"piece [{row['startFrame']},{row['endFrameExclusive']}) bytes changed")
