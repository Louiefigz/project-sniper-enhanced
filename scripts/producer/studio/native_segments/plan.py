"""The bounded revision plan, published in the immutable export request before any work starts.

Semantic edit bounds (the frames whose content changed) are reported separately from render
bounds (the delivered picture's closed GOPs those frames touch, which are the smallest ranges
that can be replaced without decoding across a reference). A whole-program closure is declared
``full-render`` and renders the whole new timeline as fixed 250-frame window owners on the same
encoder contract: each owner is short, sealed, retried within bounds and resumable, where the
single-owner default route hit its 480 s picture cap or a long-owner abort on a 49.5 s cut at
host load 20 (docs/findings/NATIVE_FINAL_SEGMENT_REVISIONS.md). Nothing is widened silently, and a
picture whose inputs are unchanged is reused exactly instead of re-rendered.
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction

from studio.native_stage_evidence import require
from studio.native_segments.long_plan import MAX_WINDOW_FRAMES, initial_long_plan, repair_long_plan  # noqa: F401

SCHEMA_VERSION = 1
SCOPE = 'native-short-revision-plan; technical reuse only, never editorial approval'
MODES = ('picture-reuse', 'segments', 'full-render')
MAX_PROBES = 1800  # the final route's own capture-inventory bound (capturePoints)
FULL_WINDOW_FRAMES = MAX_WINDOW_FRAMES  # one bounded window contract for initial Longs and revisions
# Planning estimate only, not a forecast rate: F1 phase 1 window owners took 74-93 s for 197-250 frames
# (capture 0.29 s/frame, encode 0.03 s/frame, about 4 s per owner) on the shared qualified pool
# (docs/findings/NATIVE_FINAL_SEGMENT_REVISIONS.md). Probes, assembly and delivery are extra.
ESTIMATE = {'secondsPerFrame': 0.35, 'secondsPerOwner': 4.0, 'source': 'F1 phase-1 window owners (Q1, 2026-09-28)'}


def dirty_gops(gops: list[list[int]], ranges: list[list[int]]) -> list[int]:
    """Indexes of delivered GOPs that meet any changed range (half-open)."""
    return [index for index, (start, end) in enumerate(gops)
            if any(start < high and low < end for low, high in ranges)]


def probe_frames(gops: list[list[int]], dirty: list[int], points: list[int] | None = None) -> list[int]:
    """Frames of the reused GOPs a missed dependency would show: each GOP's first and last frame, plus
    every final-route capture point inside it (``points``; a revised draft runs no capture owner)."""
    reused = [gops[index] for index in range(len(gops)) if index not in dirty]
    edges = {frame for start, end in reused for frame in (start, end - 1)}
    inside = {frame for frame in points or [] if any(start <= frame < end for start, end in reused)}
    return sorted(edges | inside)


def long_probe_schedule(canvas: dict, windows: list[dict], capture_points: list[int] | None = None) -> dict:
    """Schedule retained-window edges and declared states on the admitted Long canvas.

    Scheduling is bounded technical work. Neither selected frames nor inherited
    Short thresholds establish a qualified Long runtime isolation contract.
    """
    total = canvas['totalFrames']
    require(type(total) is int and total > 0 and Fraction(canvas['frameRate']) > 0, 'invalid Long probe clock')
    bounds = [[row['startFrame'], row['endFrame']] for row in windows]
    require(bool(bounds) and all(type(start) is int and type(end) is int and 0 <= start < end <= total
                                for start, end in bounds), 'invalid Long probe windows')
    points = capture_points or []
    require(all(type(frame) is int and 0 <= frame < total for frame in points), 'invalid Long probe state')
    frames = probe_frames(bounds, [], points)
    require(len(frames) <= MAX_PROBES, 'Long dependency probes exceed the bounded capture inventory')
    return {'canvas': dict(canvas), 'frames': frames, 'rule': 'retained-window-edges-and-declared-states-v1',
            'runtimeQualification': 'not-established'}


def probe_basis(gops: list[list[int]], dirty: list[int], points: list[int] | None) -> dict:
    """What the probes cover, for the published plan and the report."""
    edges = probe_frames(gops, dirty)
    return {'reusedGopEdges': len(edges), 'finalRouteCapturePoints': None if points is None else len(points),
            'route': 'final: the capture owner checks every capture point against the assembled picture'
                     if points is None else 'draft: capture points inside copied GOPs are dependency probes'}


def plan_mode(changes: dict, dirty: list[int]) -> str:
    """Whole-program closure renders everything; no picture change reuses the whole picture."""
    if changes['global']:
        return 'full-render'
    return 'segments' if dirty else 'picture-reuse'


def cost(windows: list[dict], probes: list[int], total_frames: int, rate: Fraction) -> dict:
    """Frames and seconds to render versus reuse, the forecast's window seconds (rendered plus probed
    frames, ``production.revision_policy``) and an owner-inclusive planning estimate."""
    rendered = sum(row['endFrame'] - row['startFrame'] for row in windows)
    owners = len(windows)
    return {'framesToRender': rendered, 'framesReused': total_frames - rendered, 'probeFrames': len(probes),
            'secondsToRender': float(Fraction(rendered) / rate), 'windowOwners': owners,
            'windowSeconds': round(float(Fraction(rendered + len(probes)) / rate), 3),
            'estimatedPictureSeconds': round(rendered * ESTIMATE['secondsPerFrame']
                                             + owners * ESTIMATE['secondsPerOwner'], 1),
            'estimate': ESTIMATE}


def full_grid(grid: dict, canvas: dict) -> dict:
    """A fresh window grid over the new timeline, on the delivered container timescale."""
    tick = Fraction(grid['timescale']) / Fraction(canvas['frameRate'])
    require(tick.denominator == 1, 'the new frame rate has no integral tick in the delivered timescale; '
            'a full re-render needs a new export, not a revision')
    total = canvas['totalFrames']
    gops = [[start, min(start + FULL_WINDOW_FRAMES, total)] for start in range(0, total, FULL_WINDOW_FRAMES)]
    return {'gops': gops, 'tick': int(tick), 'timescale': grid['timescale'], 'stream': None, 'payloads': []}


def widen(changes: dict, reason: str, total: int) -> dict:
    """The same closure declared whole-program with one more stated reason."""
    return {**changes, 'global': True, 'reasons': [*changes['reasons'], reason], 'ranges': [[0, total]]}


def revision_plan(ancestor: dict, changes: dict, grid: dict, canvas: dict) -> dict:
    """Select reuse, window renders or a declared full render from the dependency closure.

    ``changes['capturePoints']`` (a revised draft only) are the final route's capture frames.
    """
    total, points = canvas['totalFrames'], changes.get('capturePoints')
    full = full_grid(grid, canvas) if changes['global'] else grid
    gops = full['gops']
    dirty = list(range(len(gops))) if changes['global'] else dirty_gops(gops, changes['ranges'])
    mode = plan_mode(changes, dirty)
    probes = probe_frames(gops, dirty, points) if mode == 'segments' else []
    if len(probes) > MAX_PROBES:
        return revision_plan(ancestor, widen(changes, f'{len(probes)} dependency probes exceed the bound of '
                                             f'{MAX_PROBES}; the copied GOPs cannot be proved', total), grid, canvas)
    grid = full
    windows = [{'index': slot, 'gop': index, 'startFrame': gops[index][0], 'endFrame': gops[index][1]}
               for slot, index in enumerate(dirty)]
    plan = {'schemaVersion': SCHEMA_VERSION, 'scope': SCOPE, 'mode': mode,
            'ancestor': {key: ancestor[key] for key in ('attempt', 'kind', 'status', 'project', 'picture',
                                                        'video', 'audioReceipt')},
            'dependency': {'files': changes['files'], 'semanticBounds': changes['ranges'],
                           'semanticGlobal': changes['global'], 'reasons': changes['reasons'],
                           'pictureInputsSha256': changes['pictureInputs']},
            'grid': {key: grid[key] for key in ('gops', 'tick', 'timescale', 'stream', 'payloads')},
            'renderWindows': windows, 'reusedGops': [index for index in range(len(gops)) if index not in dirty],
            'probes': probes, 'probeBasis': probe_basis(gops, dirty, points) if mode == 'segments' else None,
            'cost': cost(windows, probes, total, Fraction(canvas['frameRate']))}
    plan['identity'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan
