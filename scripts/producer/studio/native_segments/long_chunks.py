"""Plan Long chunk geometry from actual scene edges, without granting execution authority.

This helper deliberately has no public export call site. Scene timing establishes
a candidate edge, not its editorial quality. Closed motion spans protect proposed
cuts; a future transition-owner contract and assigned chunk reviews must establish
continuity before this mapping can become executable. Shorts never use this plan.
"""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json, file_hash
from studio.native_region_contract import read_region_map
from studio.native_region_motion import script_text
from studio.native_region_runtime import GSAP_ASSET, implementation_pins
from studio.native_segments.dom import elements, parse
from studio.native_segments.long_plan import _bounds, _validate_previous, identity
from studio.native_stage_evidence import require

SCOPE = 'long-chunk-geometry; no render or review authority'


def _coverage(rows: list, total: int, names: tuple[str, str]) -> list[int]:
    """Require literal adjacent frame ranges that cover the original clock once."""
    require(type(rows) is list and bool(rows), 'missing chunk planning ranges')
    pairs = [[row[names[0]], row[names[1]]] for row in rows]
    require(all(type(value) is int for pair in pairs for value in pair), 'noninteger chunk planning frame')
    require(pairs[0][0] == 0 and pairs[-1][1] == total
            and all(start < end for start, end in pairs)
            and all(left[1] == right[0] for left, right in zip(pairs, pairs[1:])),
            'chunk planning ranges must cover the exact clock once')
    return [pairs[0][0], *[pair[1] for pair in pairs]]


def _assignments(rows: list, total: int) -> list[int]:
    """Retain the existing bounded creative owners; chunks create no new tasks."""
    require(type(rows) is list and 1 <= len(rows) <= 3, 'one to three creative assignments required')
    ids = [row['sectionId'] for row in rows]
    require(all(type(key) is str and key for key in ids) and len(set(ids)) == len(ids),
            'creative assignment identities must be unique')
    require(all(type(row.get('frameRange')) is list and len(row['frameRange']) == 2 for row in rows),
            'invalid creative assignment range')
    return _coverage([{'start': row['frameRange'][0], 'end': row['frameRange'][1]} for row in rows],
                     total, ('start', 'end'))


def _motions(project: Path, units: list[dict]) -> list[dict]:
    """Read already cold-validated generated declarations on the absolute program clock."""
    spans = []
    for unit in units:
        document = parse((project / unit['file']).read_text())
        declarations = [node for node in elements(document) if node.attr('data-native-section-motion')]
        tweens = json.loads(script_text(declarations[0]))['tweens'] if declarations else []
        spans.extend({'regionId': unit['id'], 'target': row['target'],
                      'frameRange': [unit['startFrame'] + row['startFrame'],
                                     unit['startFrame'] + row['endFrame']]} for row in tweens)
    return spans


def _safe(edge: int, motions: list[dict]) -> bool:
    """Avoid splitting an admitted tween; this alone is not transition approval."""
    return not any(row['frameRange'][0] < edge < row['frameRange'][1] for row in motions)


def _next_edge(start: int, candidates: list[int], rate: Fraction) -> int:
    """Prefer a declared scene edge near sixty seconds, never synthesize a timed cut."""
    preferred = [edge for edge in candidates if 45 * rate <= edge - start <= 90 * rate]
    if preferred:
        return min(preferred, key=lambda edge: (abs(edge - start - 60 * rate), edge))
    later = [edge for edge in candidates if edge - start >= 45 * rate]
    return min(later) if later else candidates[-1]


def _chunks(assignment: dict, evidence: dict, rate: Fraction) -> list[dict]:
    """Partition one creative range using only evidenced safe scene edges and its end."""
    start, end = assignment['frameRange']
    candidates = [edge for edge in evidence['sceneEdges'] if start < edge < end
                  and _safe(edge, evidence['motionSpans'])] + [end]
    result = []
    while start < end:
        stop = _next_edge(start, [edge for edge in candidates if edge > start], rate)
        duration = Fraction(stop - start, 1) / rate
        result.append({'id': 'chunk-' + identity({'sectionId': assignment['sectionId'],
                       'frameRange': [start, stop]})[:24], 'sectionId': assignment['sectionId'],
                       'frameRange': [start, stop], 'durationException': None if 45 <= duration <= 90
                       else 'creative endpoint or no safe scene edge in the preferred duration range'})
        start = stop
    return result


def _mapping(chunks: list[dict], revision: dict) -> tuple[list[int], list[dict]]:
    """Split existing encoder geometry at candidate chunk edges, retaining its owner bound."""
    edges = sorted({*[row['startFrame'] for row in revision['renderWindows']],
                    *[value for row in chunks for value in row['frameRange']]})
    _bounds(revision['canvas'], edges)
    windows = list(zip(edges, edges[1:]))
    mapped = [{**row, 'windowIndexes': [index for index, (start, end) in enumerate(windows)
               if row['frameRange'][0] <= start < end <= row['frameRange'][1]]} for row in chunks]
    return edges, mapped


def derive_long_chunks(project: Path, assignments: list[dict], revision: dict) -> dict:
    """Return a reproducible planning candidate from current Long scene and runtime bytes.

    The input revision remains untouched. Returned window indexes refer only to
    the proposed encoderBoundaries, never to existing sealed artifacts. No task,
    family invocation, counter, review, render request or approval is created.
    """
    require(not (project / 'SHORT-PROJECT.json').exists(), 'chunk planning is Long only')
    _validate_previous(revision)
    plan = bound_json(project / 'LONG-PROJECT.json')
    require(plan['canvas'] == revision['canvas'], 'chunk plan differs from the admitted Long clock')
    canvas, total = plan['canvas'], plan['canvas']['totalFrames']
    assignment_edges = _assignments(assignments, total)
    scene_edges = _coverage(plan['scenes'], total, ('startFrame', 'endFrame'))
    units = read_region_map(project, canvas)
    require(all(row['isolation']['status'] == 'scoped' for row in units),
            'chunk planning requires cold scoped runtime evidence')
    motions = _motions(project, units)
    require(all(_safe(edge, motions) for edge in assignment_edges),
            'motion crosses creative ownership; a shared transition contract is required')
    evidence = {'sceneEdges': scene_edges, 'motionSpans': motions}
    chunks = [chunk for row in assignments for chunk in _chunks(row, evidence, Fraction(canvas['frameRate']))]
    boundaries, chunks = _mapping(chunks, revision)
    files = {'LONG-PROJECT.json', 'index.html', 'REVIEW-REGIONS.json', *[row['file'] for row in units]}
    if (project / GSAP_ASSET).exists():
        files.add(GSAP_ASSET)
    result = {'schemaVersion': 1, 'scope': SCOPE, 'canvas': dict(canvas), 'evidence': evidence,
              'sourcePins': {name: file_hash(project / name) for name in sorted(files)},
              'implementationPins': implementation_pins(project),
              'creativeAssignments': [{'sectionId': row['sectionId'], 'frameRange': list(row['frameRange'])}
                                      for row in assignments],
              'encoderBoundaries': boundaries, 'chunks': chunks,
              'pending': ['transition ownership and boundary-state admission',
                          'incremental assigned chunk reviews and exact final coverage admission']}
    result['identity'] = identity(result)
    return result


def assignment_chunk_map(candidate: dict, section_id: str) -> dict:
    """Freeze assignment-local geometry, without transferring global or sibling approval.

    Absolute window ranges avoid indexing shifts in earlier creative assignments.
    A future admission reader must match these against actual current window
    versions and separately admit transitions; this record remains planning-only.
    """
    require(candidate.get('scope') == SCOPE and candidate.get('identity') == identity(
            {key: value for key, value in candidate.items() if key != 'identity'}), 'chunk candidate changed')
    rows = [row for row in candidate['creativeAssignments'] if row['sectionId'] == section_id]
    require(len(rows) == 1, 'chunk candidate lacks one matching creative assignment')
    start, end = rows[0]['frameRange']
    windows = list(zip(candidate['encoderBoundaries'], candidate['encoderBoundaries'][1:]))
    chunks = [{key: value for key, value in row.items() if key != 'windowIndexes'} |
              {'windowRanges': [list(windows[index]) for index in row['windowIndexes']]}
              for row in candidate['chunks'] if row['sectionId'] == section_id]
    result = {'schemaVersion': 1, 'scope': SCOPE, **rows[0], 'chunks': chunks,
              'canvas': dict(candidate['canvas']),
              'boundaryEvidence': {'sceneEdges': [edge for edge in candidate['evidence']['sceneEdges']
                                                 if start <= edge <= end],
                                   'motionSpans': [row for row in candidate['evidence']['motionSpans']
                                                   if row['frameRange'][0] < end
                                                   and row['frameRange'][1] > start]},
              'pending': list(candidate['pending'])}
    result['identity'] = identity(result)
    return result
