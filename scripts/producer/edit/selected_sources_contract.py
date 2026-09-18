"""Plan bounded reusable source sections without changing editorial clocks."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import math
import re

from cut_preview_io import file_hash, real_directory
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, require

MAX_SOURCES = 128
MAX_RANGES = 256
MAX_SELECTED_SECONDS = 3600
MAX_HANDLE_SECONDS = 5
MAX_KEYFRAME_LEAD_SECONDS = 30


def seconds(value: object) -> Fraction:
    """Accept finite nonnegative JSON seconds without binary-float authority."""
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'selected-source seconds must be finite and nonnegative')
    return Fraction(str(value))


def checked_source(row: dict) -> dict:
    """Bind each logical asset to unchanged original bytes, never a URL."""
    require(type(row) is dict and set(row) == {'file', 'path', 'sha256'},
            'selected source needs file, path and sha256')
    require(isinstance(row['sha256'], str)
            and re.fullmatch('[a-f0-9]{64}', row['sha256']) is not None,
            'selected source hash is invalid')
    require(row['file'] == f"assets/{row['sha256']}.mp4", 'source alias must be content addressed')
    require(isinstance(row['path'], str), 'selected source path must be a string')
    source = Path(row['path'])
    real_directory(source.parent)
    require(file_hash(source, MAX_NATIVE_FILE_BYTES) == row['sha256'], 'selected source changed')
    return dict(row)


def selection_request(value: dict) -> dict:
    """Validate already chosen ranges; this function does not select or shorten speech."""
    require(type(value) is dict and set(value) == {'schemaVersion', 'sources', 'ranges', 'handleSeconds'},
            'selected-source request has missing or unknown fields')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1,
            'unsupported selected-source request')
    require(type(value['sources']) is list and 1 <= len(value['sources']) <= MAX_SOURCES,
            'selected source inventory is empty or too large')
    sources = [checked_source(row) for row in value['sources']]
    files = [row['file'] for row in sources]
    require(len(set(files)) == len(files), 'selected sources duplicate an alias')
    handles = seconds(value['handleSeconds'])
    require(handles <= MAX_HANDLE_SECONDS, 'selected source handles exceed five seconds')
    ranges = value['ranges']
    require(type(ranges) is list and 1 <= len(ranges) <= MAX_RANGES,
            'selected ranges are empty or too numerous')
    for row in ranges:
        checked_range(row, files)
    require(sum(seconds(row['end']) - seconds(row['start']) for row in ranges)
            <= MAX_SELECTED_SECONDS, 'selected-source duration exceeds one hour')
    require(set(files) == {row['sourceFile'] for row in ranges}, 'unused source in selected package')
    return {**value, 'sources': sources}


def checked_range(row: dict, files: list[str]) -> None:
    """Require one explicit nonempty source interval."""
    require(type(row) is dict and set(row) == {'sourceFile', 'start', 'end'},
            'selected range has missing or unknown fields')
    require(row['sourceFile'] in files, 'selected range cites an unknown source')
    require(seconds(row['end']) > seconds(row['start']), 'selected range is empty or reversed')


def source_sections(request: dict, durations: dict[str, Fraction]) -> list[dict]:
    """Merge overlapping handles so repeated views reuse the same physical clip."""
    sections = []
    handles = seconds(request['handleSeconds'])
    for source in request['sources']:
        duration = Fraction(durations[source['file']])
        ranges = sorted((seconds(row['start']), seconds(row['end'])) for row in request['ranges']
                        if row['sourceFile'] == source['file'])
        require(all(end <= duration for _start, end in ranges), 'selection exceeds source duration')
        merged = merge_sections(ranges, handles, duration)
        sections.extend({'sourceFile': source['file'], 'start': str(start), 'end': str(end)}
                        for start, end in merged)
    return sections


def merge_sections(ranges: list[tuple[Fraction, Fraction]], handles: Fraction,
                   duration: Fraction) -> list[tuple[Fraction, Fraction]]:
    """Use rational boundaries, with audio handles aligned down to 48 kHz samples."""
    merged: list[tuple[Fraction, Fraction]] = []
    for start, end in ranges:
        start = Fraction(max(0, start - handles) * 48000 // 1, 48000)
        end = min(duration, end + handles)
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            continue
        merged.append((start, end))
    return merged


def source_pins(request: dict) -> dict[str, str]:
    """Keep original identity separate from small executable media."""
    return {row['path']: row['sha256'] for row in request['sources']}
