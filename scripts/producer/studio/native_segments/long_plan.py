"""Initial Long section identities and explicit repair closure, without a Short ancestor.

This is a technical plan. It neither creates task authority nor transfers editorial
approval. Callers provide the digest of their complete admitted picture dependency
closure, including the implementation and encoder. Repair closure must come from
the existing dependency reader comparing immutable project snapshots.
"""
from __future__ import annotations

import hashlib
import json
import re
from fractions import Fraction

from studio.native_segments.manifest import MAX_PIECES
from studio.native_stage_evidence import require

SCOPE = 'native-long-section-plan; technical reuse only, never editorial approval'
MAX_WINDOW_FRAMES = 250


def identity(value: object) -> str:
    """Hash canonical structured section metadata without mutable output paths."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _sha(value: object) -> None:
    """Require a real SHA256 identity rather than an unbound label."""
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None,
            'section picture dependency identity must be SHA256')


def _bounds(canvas: dict, boundaries: list[int] | None) -> list[int]:
    """Validate exact coverage and the bounded per-owner frame allowance."""
    total = canvas['totalFrames']
    require(type(total) is int and total > 0, 'invalid Long frame count')
    rate = Fraction(canvas['frameRate'])
    require(0 < rate <= 120, 'invalid Long frame rate')
    values = list(range(0, total, MAX_WINDOW_FRAMES)) + [total] if boundaries is None else boundaries
    require(isinstance(values, list) and 2 <= len(values) <= MAX_PIECES + 1
            and all(type(value) is int for value in values), 'invalid Long section boundaries')
    require(values[0] == 0 and values[-1] == total
            and all(0 < end - start <= MAX_WINDOW_FRAMES for start, end in zip(values, values[1:])),
            'Long sections must cover the exact clock with bounded, ordered frame ranges')
    return values


def _window(index: int, bounds: tuple[int, int], source: str) -> dict:
    """Assign a stable range owner and bind the complete initial picture closure."""
    start, end = bounds
    return {'index': index, 'gop': index, 'startFrame': start, 'endFrame': end,
            'id': f'section-{index:03d}', 'generation': 1,
            'inputIdentity': identity({'pictureInputs': source, 'frames': [start, end]})}


def initial_long_plan(canvas: dict, picture_inputs: str, boundaries: list[int] | None = None) -> dict:
    """Partition one admitted initial Long on its absolute frame clock.

    Args:
        canvas: The validated Long canvas.
        picture_inputs: Digest of all admitted picture inputs, code and tools.
        boundaries: Optional complete ordered frame boundaries, including zero/end.

    Returns:
        Immutable-request metadata compatible with the existing section encoder.
    """
    _sha(picture_inputs)
    values, rate = _bounds(canvas, boundaries), Fraction(canvas['frameRate'])
    gops = [list(pair) for pair in zip(values, values[1:])]
    source = identity({'inputs': picture_inputs, 'canvas': canvas})
    windows = [_window(index, tuple(pair), source) for index, pair in enumerate(gops)]
    plan = {'schemaVersion': 1, 'scope': SCOPE, 'mode': 'initial-long',
            'canvas': dict(canvas), 'dependency': {'pictureInputsSha256': picture_inputs,
                'semanticBounds': [[0, canvas['totalFrames']]], 'semanticGlobal': True,
                'files': [], 'reasons': ['initial Long picture; no ancestor']},
            'grid': {'gops': gops, 'tick': rate.denominator, 'timescale': rate.numerator,
                     'stream': None, 'payloads': []},
            'renderWindows': windows, 'reusedGops': [], 'probes': [], 'probeBasis': None}
    plan['identity'] = identity(plan)
    return plan


def _validate_previous(previous: dict) -> None:
    """Reject mutable or malformed manifests before carrying section identities forward."""
    require(previous.get('scope') == SCOPE and previous.get('mode') == 'initial-long',
            'repair requires an initial Long section manifest')
    require(previous.get('identity') == identity({key: value for key, value in previous.items()
                                                if key not in {'identity', 'windowDonors'}}),
            'Long section manifest changed')
    windows = previous['renderWindows']
    require(all(left['endFrame'] == right['startFrame'] for left, right in zip(windows, windows[1:])),
            'Long section manifest has a frame gap or overlap')
    boundaries = [row['startFrame'] for row in windows] + [windows[-1]['endFrame']]
    _bounds(previous['canvas'], boundaries)
    require(previous['grid']['gops'] == [[row['startFrame'], row['endFrame']] for row in windows],
            'Long section manifest grid differs')
    for index, row in enumerate(windows):
        require(row['index'] == row['gop'] == index and row['id'] == f'section-{index:03d}'
                and type(row['generation']) is int and row['generation'] > 0, 'invalid Long section identity')
        _sha(row['inputIdentity'])


def _changed_indexes(previous: dict, changes: dict) -> list[int]:
    """Use a validated dependency closure; absence of explicit locality fails closed."""
    from studio.native_segments.plan import dirty_gops
    require(type(changes.get('global')) is bool and isinstance(changes.get('ranges'), list),
            'repair requires an explicit dependency closure')
    total = previous['canvas']['totalFrames']
    for pair in changes['ranges']:
        require(isinstance(pair, list) and len(pair) == 2 and all(type(value) is int for value in pair)
                and 0 <= pair[0] < pair[1] <= total, 'invalid repair dependency range')
    if changes['global']:
        return list(range(len(previous['renderWindows'])))
    return dirty_gops(previous['grid']['gops'], changes['ranges'])


def repair_long_plan(previous: dict, changes: dict, canvas: dict) -> dict:
    """Invalidate affected picture sections and neighboring joins; audio stays independent.

    Changes use ``dependency.picture_changes``'s result. Callers must additionally
    widen when renderer/tool or other non-project picture dependencies changed.
    Unaffected identities preserve technical reuse only, never editorial approval.
    """
    _validate_previous(previous)
    _sha(changes['pictureInputs'])
    if canvas != previous['canvas']:
        return initial_long_plan(canvas, changes['pictureInputs'])
    dirty = _changed_indexes(previous, changes)
    windows = [_repaired_window(row, dirty, changes['pictureInputs']) for row in previous['renderWindows']]
    joins = sorted({edge for index in dirty for edge in (index - 1, index)
                    if 0 <= edge < len(windows) - 1})
    result = {**{key: value for key, value in previous.items() if key != 'windowDonors'},
              'renderWindows': windows,
              'dependency': {'pictureInputsSha256': changes['pictureInputs'],
                  'semanticBounds': changes['ranges'], 'semanticGlobal': changes['global'],
                  'files': changes['files'], 'reasons': changes['reasons']},
              'repair': {'previousIdentity': previous['identity'], 'affectedSections': dirty,
                         'recheckJoins': joins, 'technicalReuseSections': [row['index'] for row in windows
                                                                         if row['index'] not in dirty]}}
    result['identity'] = identity({key: value for key, value in result.items() if key != 'identity'})
    return result


def _repaired_window(row: dict, dirty: list[int], source: str) -> dict:
    """Preserve compatible section identity or advance the changed owner's generation."""
    if row['index'] not in dirty:
        return dict(row)
    generation = row['generation'] + 1
    return {**row, 'generation': generation,
            'inputIdentity': identity({'previous': row['inputIdentity'], 'generation': generation,
                                       'pictureInputs': source})}
