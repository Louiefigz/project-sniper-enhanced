"""Event-driven moving-preview windows, navigation index and workload (packet schema 2).

Units: each mapped composition is a region unit; program time outside every region
is split into window units, one per merged event window, so an edit invalidates
only the windows that can show it. A changed region short enough for one window is
shown whole with two seconds of context; a longer one around each of its risk
events, bounds and midpoint. Windows merge when close, never exceed twelve seconds,
and are capped by count and total frames; every event a changed unit owns but no
window shows is reported as uncovered and deferred to full-output review. The
schedule decides preview coverage only; it never grants an editorial review.
"""
from __future__ import annotations

from fractions import Fraction

from cut_preview_io import digest

SCHEDULE_RULE = 'risk-events-v1'
WINDOW_SECONDS, UNIT_PAD_SECONDS, EVENT_PAD_SECONDS, MERGE_GAP_SECONDS = 12, 2, 1, 1
MAX_WINDOWS, MAX_PREVIEW_SECONDS = 6, 30
PRIORITY = {'title-entrance': 0, 'title-exit': 0, 'source-join': 1, 'composition-entrance': 1,
            'composition-exit': 1, 'region-start': 1, 'region-end': 1, 'hold-start': 2, 'hold-end': 2,
            'checkpoint': 2, 'audio-gain': 2, 'caption-suppression-start': 2, 'caption-suppression-end': 2,
            'motion-cue': 3, 'visual-element': 3, 'picture-view': 3,
            'caption-view': 4, 'composition-midpoint': 4, 'unit-boundary': 5, 'unit-midpoint': 5,
            'program-start': 5, 'program-end': 5}


def clock(canvas: dict) -> dict:
    """Frame-count parameters from the exact canvas rate."""
    rate = Fraction(canvas['frameRate'])
    frames = {name: max(1, round(rate * seconds)) for name, seconds in (
        ('unit', UNIT_PAD_SECONDS), ('event', EVENT_PAD_SECONDS), ('gap', MERGE_GAP_SECONDS),
        ('window', WINDOW_SECONDS), ('budget', MAX_PREVIEW_SECONDS))}
    return {'rate': rate, 'total': canvas['totalFrames'], **frames}


def unit_targets(unit: dict, events: list[dict]) -> dict[int, set[str]]:
    """Every event inside a unit, plus (except for window units) its bounds and midpoint."""
    low, high = unit['startFrame'], unit['endFrame']
    targets: dict[int, set[str]] = {}
    for row in events:
        if low <= row['frame'] < high:
            targets.setdefault(row['frame'], set()).update(row['kinds'])
    if unit.get('kind') == 'window':
        return targets
    for frame, kind in ((low, 'unit-boundary'), (high - 1, 'unit-boundary'), ((low + high) // 2, 'unit-midpoint')):
        targets.setdefault(frame, set()).add(kind)
    return targets


def unit_candidates(unit: dict, events: list[dict], parameters: dict) -> list[tuple[int, int, int]]:
    """A window unit is its own range; short units whole; otherwise one padded window per target.

    Regions pad into their neighbours for context. Gaps stay inside themselves, so a window
    outside every composition never shows, or depends on, a composition's frames.
    """
    low, high, total = unit['startFrame'], unit['endFrame'], parameters['total']
    if unit.get('kind') == 'window':
        kinds = [kind for row in events if low <= row['frame'] < high for kind in row['kinds']]
        return [(low, high, min([PRIORITY.get(kind, 5) for kind in kinds] or [5]))]
    first, last = (low, high) if unit.get('kind') == 'gap' else (0, total)
    if high - low + 2 * parameters['unit'] <= parameters['window']:
        return [(max(first, low - parameters['unit']), min(last, high + parameters['unit']), 0)]
    pad = parameters['event']
    return [(max(first, frame - pad), min(last, frame + pad), min(PRIORITY.get(kind, 5) for kind in kinds))
            for frame, kinds in sorted(unit_targets(unit, events).items())]


def merge(candidates: list[tuple[int, int, int]], parameters: dict) -> list[tuple[int, int, int]]:
    """Join overlapping or near windows within one window length; never render a frame twice."""
    merged: list[list[int]] = []
    for start, end, priority in sorted(set(candidates)):
        last = merged[-1] if merged else [0, 0, priority]
        joined = merged and start <= last[1] + parameters['gap'] and max(end, last[1]) - last[0] <= parameters['window']
        start = max(start, last[1]) if merged else start  # Unmergeable overlap continues after the window.
        if joined or start >= end:
            last[1], last[2] = max(end, last[1]), min(priority, last[2])
        else:
            merged.append([start, end, priority])
    return [tuple(row) for row in merged]


def budget(windows: list[tuple[int, int, int]], parameters: dict) -> list[tuple[int, int, int]]:
    """Drop the least important windows until count and frame volume fit their bounds."""
    kept = list(windows)
    while len(kept) > MAX_WINDOWS or sum(end - start for start, end, _ in kept) > parameters['budget']:
        kept.remove(max(kept, key=lambda row: (row[2], row[1] - row[0], row[0])))
    return kept


def preview_schedule(packet: dict, previous: dict | None = None) -> dict:
    """Windows for changed units, with a navigation index and explicit uncovered events."""
    parameters = clock(packet['canvas'])
    old = {row['id']: row['hash'] for row in (previous or {}).get('units', [])}
    changed = [row for row in packet['units'] if old.get(row['id']) != row['hash']]
    candidates, targets = [], {}
    for unit in changed:
        for frame, kinds in unit_targets(unit, packet['events']).items():
            targets.setdefault(frame, set()).update(kinds)
        candidates += unit_candidates(unit, packet['events'], parameters)
    windows = budget(merge(candidates, parameters), parameters)
    unseen = [row['id'] for row in changed
              if not any(start < row['endFrame'] and row['startFrame'] < end for start, end, _ in windows)]
    return {'rule': SCHEDULE_RULE, 'changedUnits': [row['id'] for row in changed], 'unpreviewedUnits': unseen,
            'windows': [{'startFrame': start, 'endFrame': end} for start, end, _ in windows],
            **navigation(targets, windows, parameters['rate']), 'workload': workload(windows, parameters['rate'])}


def navigation(targets: dict[int, set[str]], windows: list[tuple], rate: Fraction) -> dict:
    """Where each risk event appears in the preview clips, or why it does not."""
    shown, uncovered = [], []
    for frame, kinds in sorted(targets.items()):
        row = {'frame': frame, 'seconds': float(Fraction(frame) / rate), 'kinds': sorted(kinds)}
        index = next((index for index, (start, end, _) in enumerate(windows) if start <= frame < end), None)
        if index is None:
            uncovered.append({**row, 'reason': 'preview-window-budget', 'deferredTo': 'full-output-review'})
        else:
            offset = frame - windows[index][0]
            shown.append({**row, 'window': index, 'offsetFrame': offset, 'offsetSeconds': float(Fraction(offset) / rate)})
    return {'navigation': shown, 'uncovered': uncovered}


def workload(windows: list[tuple], rate: Fraction) -> dict:
    """The planned preview cost a deadline forecast charges before any owner starts."""
    frames = sum(end - start for start, end, _ in windows)
    return {'windows': len(windows), 'sections': 2 * len(windows), 'frames': frames,
            'seconds': float(Fraction(frames) / rate)}


def gaps(rows: list[dict], total: int) -> list[dict]:
    """Program intervals outside every mapped composition."""
    found, cursor = [], 0
    for start, end in sorted((row['startFrame'], row['endFrame']) for row in rows):
        if start > cursor:
            found.append({'kind': 'gap', 'startFrame': cursor, 'endFrame': start})
        cursor = max(cursor, end)
    if cursor < total:
        found.append({'kind': 'gap', 'startFrame': cursor, 'endFrame': total})
    return found


def plan_units(rows: list[dict], events: list[dict], parameters: dict) -> list[dict]:
    """Region units plus one window unit per merged event window of every gap."""
    units = [{'id': row['id'], 'kind': 'region', 'startFrame': row['startFrame'], 'endFrame': row['endFrame']}
             for row in rows]
    for gap in gaps(rows, parameters['total']):
        for start, end, _priority in merge(unit_candidates(gap, events, parameters), parameters):
            units.append({'id': f'project-window-{start}-{end}', 'kind': 'window', 'startFrame': start, 'endFrame': end})
    return units


def dependency_units(rows: list[dict], context: tuple[dict, str], sources: dict, events: list[dict]) -> list[dict]:
    """Bind each unit to every composition visible anywhere its uncapped windows could show."""
    canvas, base = context
    if not rows:
        return [{'id': 'project', 'kind': 'project', 'startFrame': 0, 'endFrame': canvas['totalFrames'], 'hash': base}]
    parameters, result = clock(canvas), []
    for unit in plan_units(rows, events, parameters):
        spans = merge(unit_candidates(unit, events, parameters), parameters)
        visible = {row['file']: sources[row['file']] for row in rows
                   if any(row['startFrame'] < end and start < row['endFrame'] for start, end, _ in spans)}
        region = next((row for row in rows if row['id'] == unit['id']), unit)
        result.append({**unit, 'hash': digest({'shared': base, 'region': region, 'sources': visible})})
    return result


def schedule_summary(packet: dict, previous: dict | None) -> dict:
    """Fields recorded in motion-previews.json; schema-1 (Long) packets keep their old receipt."""
    if packet.get('schemaVersion') != 2:
        return {}
    schedule = preview_schedule(packet, previous)
    return {'schedule': {key: schedule[key] for key in ('rule', 'changedUnits', 'unpreviewedUnits', 'windows', 'workload')},
            'navigation': schedule['navigation'], 'uncoveredEvents': schedule['uncovered']}
