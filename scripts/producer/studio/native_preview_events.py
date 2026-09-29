"""Risk events that a native Short moving preview must show, derived from the executable plan.

Events are frames on the output clock where review failures cluster in retained
runs: source joins, title entrance/exit, composition mount start/end, authored
hold boundaries and checkpoints, visual element and motion cue boundaries,
reasoned caption-suppression edges and audio gain window edges. They schedule preview windows and a navigation index;
they are never a dependency hash, approval or proof that a frame is correct.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from fractions import Fraction

from studio.native_stage_evidence import require

MAX_EVENTS = 1024


def _frame(value: object, total: int) -> int | None:
    """Accept only exact in-range output frames; malformed plan data never becomes an event."""
    return value if type(value) is int and 0 <= value < total else None


def _canvas_events(canvas: dict, add: Callable[[object, str], None]) -> None:
    """Joins, crops, captions, native elements and motion cues declared on the output clock."""
    for segment in canvas.get('segments', [])[1:]:
        add(segment.get('startFrame'), 'source-join')
    for view in canvas.get('pictureViews', []):
        add(view.get('startFrame'), 'picture-view')
        add(view.get('endFrame'), 'picture-view')
    for view in canvas.get('captionViews', []):
        add(view.get('startFrame'), 'caption-view')
        add(view.get('endFrame'), 'caption-view')
    for window in canvas.get('captionSuppressions') or []:
        add(window.get('startFrame'), 'caption-suppression-start')
        add(window.get('endFrame'), 'caption-suppression-end')
    for item in [*canvas.get('text', []), *canvas.get('shapes', [])]:
        add(item.get('startFrame'), 'visual-element')
        add(item.get('endFrame'), 'visual-element')
    for cue in canvas.get('motion', []):
        start = cue.get('startFrame')
        add(start, 'motion-cue')
        if type(start) is int and type(cue.get('durationFrames')) is int:
            add(start + cue['durationFrames'], 'motion-cue')
    title = canvas.get('titleCard')
    if title:
        add(0, 'title-entrance')
        add(title.get('endFrame'), 'title-exit')


def _mount_events(plan: dict, mounts: list[dict], add: Callable[[object, str], None]) -> None:
    """Entrance, midpoint and exit of every root-clock catalog mount, title mounts named as such."""
    from studio.native_short_regions import mount_frames
    rate, title = Fraction(plan['canvas']['frameRate']), (plan.get('catalogTitle') or {}).get('file')
    for mount in mounts:
        frames = None if mount['__timed__'] else mount_frames(mount, rate)
        if frames is None:
            continue
        kind = 'title' if mount['data-composition-src'] == title else 'composition'
        add(frames[0], f'{kind}-entrance')
        add(frames[1], f'{kind}-exit')
        add((frames[0] + frames[1]) // 2, 'composition-midpoint')


def _authored_events(plan: dict, add: Callable[[object, str], None]) -> None:
    """Hold starts/ends and story checkpoints are the plan's own visible-state promises."""
    for hold in ((plan.get('strategy') or {}).get('pacing') or {}).get('holds', []):
        add(hold.get('startFrame'), 'hold-start')
        add(hold.get('endFrame'), 'hold-end')
    for check in plan.get('expectations') or []:
        add(check.get('frame'), 'checkpoint')


def _audio_events(plan: dict, add: Callable[[object, str], None]) -> None:
    """Gain window edges, floored onto the output frame clock without rounding."""
    rate = Fraction(plan['canvas']['frameRate'])
    edges = [window.get(key) for window in (plan.get('audioFinishing') or {}).get('audioGain') or []
             for key in ('outStart', 'outEnd')]
    for value in edges:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            add(math.floor(Fraction(value) * rate), 'audio-gain')


def risk_events(plan: dict, rows: list[dict], mounts: list[dict]) -> list[dict]:
    """Merge every declared risk frame into one sorted, bounded event list."""
    total = plan['canvas']['totalFrames']
    found: dict[int, set[str]] = {}

    def add(value: object, kind: str) -> None:
        frame = _frame(value, total)
        if frame is not None:
            found.setdefault(frame, set()).add(kind)

    add(0, 'program-start')
    add(total - 1, 'program-end')
    _canvas_events(plan['canvas'], add)
    _mount_events(plan, mounts, add)
    _authored_events(plan, add)
    _audio_events(plan, add)
    for row in rows:
        add(row['startFrame'], 'region-start')
        add(row['endFrame'], 'region-end')
    require(len(found) <= MAX_EVENTS, 'Native preview risk events exceed their bound')
    return [{'frame': frame, 'kinds': sorted(kinds)} for frame, kinds in sorted(found.items())]
