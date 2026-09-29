"""Adapter-neutral retained JPEG inventories; callers supply geometry and ownership limits.

This reader grants no render, source, revision or editorial authority. Short and
Long adapters must independently admit their own owner seals and dependency
closure before using the returned immutable frame pins.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from cut_preview_io import file_hash
from studio.native_stage_evidence import require

KIND = 'native-retained-capture-frames'
ENCODING = 'jpeg95-matching-opaque-render'
KEYS = {'schemaVersion', 'kind', 'canvas', 'frameRange', 'encoding', 'frames', 'sessions'}


@dataclass(frozen=True)
class CaptureContract:
    """One adapter's canonical frame root, exact canvas/range, and count/byte ceilings."""

    root: Path
    canvas: dict
    frame_range: tuple[int, int]
    limits: tuple[int, int]


def frame_partition(bounds: tuple[int, int], dirty: list[list[int]], maximum: int) -> tuple[list[int], list[int]]:
    """Intersect sorted half-open semantic ranges with one bounded encoder window."""
    start, end = bounds
    require(type(start) is int and type(end) is int and 0 <= start < end
            and type(maximum) is int and 0 < end - start <= maximum, 'invalid retained frame window')
    require(type(dirty) is list and len(dirty) <= 4096, 'unbounded dirty frame ranges')
    cursor, changed = 0, set()
    for row in dirty:
        require(type(row) is list and len(row) == 2 and all(type(value) is int for value in row)
                and cursor <= row[0] < row[1], 'dirty frame ranges overlap or are unordered')
        changed.update(range(max(start, row[0]), min(end, row[1])))
        cursor = row[1]
    return sorted(changed), [frame for frame in range(start, end) if frame not in changed]


def verify_frame(row: dict, contract: CaptureContract) -> str:
    """Check exact absolute identity, canonical regular bytes and the adapter's size ceiling."""
    require(type(row) is dict and set(row) == {'frame', 'path', 'sha256', 'bytes', 'origin'},
            'invalid retained frame row')
    frame = row['frame']
    require(type(frame) is int and contract.frame_range[0] <= frame < contract.frame_range[1]
            and row['origin'] in ('captured', 'retained'), 'invalid retained frame identity')
    file = contract.root / f'frame_{frame:06d}.jpg'
    require(row['path'] == str(file) and file.is_absolute() and file.resolve(strict=True) == file,
            'retained frame escapes its canonical inventory')
    require(type(row['bytes']) is int and 0 < row['bytes'] <= contract.limits[1]
            and type(row['sha256']) is str and re.fullmatch('[a-f0-9]{64}', row['sha256']) is not None,
            'invalid retained frame bytes or digest')
    stat = file.lstat()
    require(file.is_file() and not file.is_symlink() and stat.st_nlink == 1 and stat.st_size == row['bytes'],
            'retained frame is linked, resized or nonregular')
    require(file_hash(file, maximum=contract.limits[1]) == row['sha256'], 'retained frame changed')
    return str(file)


def verify_sessions(sessions: list[dict], captured: list[int], maximum: int) -> None:
    """Every actually captured frame belongs to one disposed bounded native session."""
    require(type(sessions) is list and len(sessions) <= maximum, 'invalid retained capture sessions')
    observed = []
    for session in sessions:
        require(type(session) is dict and type(session.get('frames')) is list
                and 0 < len(session['frames']) <= 48
                and all(type(frame) is int for frame in session['frames']), 'invalid capture session inventory')
        require(all(session.get(key) is True for key in ('sessionClosed', 'browserPoolDrained', 'serverClosed'))
                and type(session.get('transport')) is dict and type(session['transport'].get('errors')) is int
                and session['transport']['errors'] == 0,
                'retained capture session did not dispose cleanly')
        observed.extend(session['frames'])
    require(sorted(observed) == captured, 'retained capture session coverage differs')


def read_frame_inventory(value: dict, contract: CaptureContract) -> dict[str, str]:
    """Rehash a complete ordered frame manifest under explicit adapter limits, never Short defaults."""
    start, end = contract.frame_range
    require(type(contract.limits) is tuple and len(contract.limits) == 2
            and all(type(item) is int and item > 0 for item in contract.limits)
            and type(start) is int and type(end) is int and 0 <= start < end <= contract.canvas['totalFrames']
            and end - start <= contract.limits[0], 'retained frame contract exceeds adapter bounds')
    require(type(value) is dict and set(value) == KEYS and type(value['schemaVersion']) is int
            and value['schemaVersion'] == 1 and value['kind'] == KIND and value['encoding'] == ENCODING
            and value['canvas'] == contract.canvas and value['frameRange'] == [start, end],
            'retained frame inventory contract differs')
    frames = value['frames']
    require(type(frames) is list and len(frames) == end - start and all(type(row) is dict for row in frames)
            and [row.get('frame') for row in frames] == list(range(start, end)), 'retained frame inventory is incomplete')
    pins = {verify_frame(row, contract): row['sha256'] for row in frames}
    require({str(file) for file in contract.root.iterdir()} == set(pins), 'retained frame directory has unlisted entries')
    captured = [row['frame'] for row in frames if row['origin'] == 'captured']
    verify_sessions(value['sessions'], captured, contract.limits[0])
    return pins
