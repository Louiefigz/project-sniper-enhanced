"""Strict landscape export contract on the existing native frame/sample clock."""
from __future__ import annotations

from fractions import Fraction
from math import ceil
from pathlib import Path
import re

from cut_preview_io import bound_json
from studio.long_sources_html import inspect_html, local_asset, number
from studio.native_short_dialogue import clock
from studio.native_stage_evidence import require
from studio.native_workload import workload_budget


def read_long_plan(project: Path) -> dict:
    """Reject gaps, ambiguous audio, clock drift and unreviewable scene ownership."""
    plan = bound_json(project / 'LONG-PROJECT.json')
    require(plan.get('schemaVersion') == 1, 'unsupported long export schema')
    canvas = plan['canvas']
    budget = workload_budget(canvas)
    root, media = inspect_html((project / 'index.html').read_text())
    width, height = canvas['width'], canvas['height']
    require(type(width) is int and type(height) is int and width > height > 0
            and width <= 3840 and height <= 2160 and width % 2 == height % 2 == 0,
            'long export requires even landscape dimensions through 3840×2160')
    require(number(root['data-width']) == width and number(root['data-height']) == height,
            'long canvas differs from HTML')
    duration = Fraction(canvas['totalFrames'], 1) / clock(canvas).fps.fraction
    require(abs(number(root['data-duration']) - duration) <= Fraction(1, 1000000),
            'long root duration differs from integer output frames')
    validate_scenes(plan, media)
    audio = [row for row in media if row.kind == 'audio']
    require(len(audio) == 1, 'long export requires one explicit complete-program float WAV')
    attrs = audio[0].attributes
    require(attrs.get('data-volume', '1') == '1' and 'muted' not in attrs,
            'long WAV is premixed; HTML audio gain/muting is unsupported')
    text = (project / 'index.html').read_text()
    require('<hf-audio-' not in text and not re.search(r'\bvolume\s*:', text),
            'long WAV is premixed; HTML audio effects/automation require explicit adaptation')
    require(attrs['src'] == local_asset(plan['audio']['file'])
            and attrs['src'].endswith('.wav') and number(attrs['data-start']) == 0
            and number(attrs.get('data-media-start', '0')) == 0
            and abs(number(attrs['data-duration']) - duration) <= Fraction(1, 1000000),
            'audio must preserve the complete program clock')
    require(set(plan['audio']) == {'file'}, 'apply cleanup to the explicit premaster before export')
    plan['budget'] = budget
    return plan


def validate_scenes(plan: dict, media: list) -> None:
    """Require contiguous scene coverage and explicit expected media at every cut."""
    scenes, canvas = plan['scenes'], plan['canvas']
    require(isinstance(scenes, list) and 0 < len(scenes) <= 256, 'invalid long scene inventory')
    cursor = 0
    videos = {row.attributes['id']: row for row in media if row.kind == 'video'}
    for scene in scenes:
        require(set(scene) == {'startFrame', 'endFrame', 'mediaIds'}, 'unknown long scene fields')
        start, end = scene['startFrame'], scene['endFrame']
        require(type(start) is int and type(end) is int and start == cursor
                and start < end <= canvas['totalFrames'], 'long scenes must cover every frame exactly once')
        ids = scene['mediaIds']
        require(isinstance(ids, list) and len(ids) == len(set(ids)) and set(ids) <= videos.keys(),
                'scene references duplicate or unknown media')
        cursor = end
    require(cursor == canvas['totalFrames'], 'long scenes omit the ending')
    rate = clock(canvas).fps.fraction
    windows = {key: (ceil(number(row.attributes['data-start']) * rate),
        ceil((number(row.attributes['data-start']) + number(row.attributes['data-duration'])) * rate))
        for key, row in videos.items()}
    for scene in scenes:
        active = set()
        for key, (start, end) in windows.items():
            if max(start, scene['startFrame']) >= min(end, scene['endFrame']):
                continue
            require(start <= scene['startFrame'] and end >= scene['endFrame'],
                    'scene omits an internal video boundary')
            active.add(key)
        require(active == set(scene['mediaIds']), 'scene media ownership differs from literal video windows')


def long_audio_canvas(plan: dict) -> dict:
    """Keep dialogue review sections independent of picture-only scene changes."""
    return {**plan['canvas'], 'segments': [{'startFrame': 0,
                                          'endFrameExclusive': plan['canvas']['totalFrames']}]}


def sample_frame_count(plan: dict) -> int:
    """Reserve the exact seam/interior reference count including reverse visits."""
    canvas = plan['canvas']
    total, rate = canvas['totalFrames'], clock(canvas).fps.fraction
    frames = {0, total - 1}
    boundaries = {value for scene in plan['scenes'] for value in (scene['startFrame'], scene['endFrame'])}
    frames.update(value + delta for value in boundaries for delta in range(-2, 3)
                  if 0 <= value + delta < total)
    frames.update(range(0, total, max(1, int(rate * 2))))
    require(len(frames) <= 3000, 'long sample schedule exceeds its bound')
    return len(frames) * 2
