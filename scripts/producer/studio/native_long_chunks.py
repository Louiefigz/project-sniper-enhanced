"""Long-only chunk/transition admission through existing independent prebuild authority.

Authored purposes and continuity assessments are recorded judgments. Cold readers
verify their exact source, ownership and timing bindings; they do not prove that
a reviewer watched playback or that technical encoder cuts preserve visual state.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_long_chunk_evidence import (CONTRACT, boundary_frames, boundary_neighbors,
                                              chunk_geometry, transition_evidence)
from studio.native_runtime import digest
from studio.native_segments.long_plan import _validate_previous, identity
from studio.native_stage_evidence import require
from studio.production.section_plan import pin_file, read_plan

KIND = 'native-long-chunk-admission'
ASSIGNMENT_KEYS = {'sectionId', 'generation', 'inputIdentity', 'frameRange', 'mapIdentity', 'chunks', 'transitionIds'}
TRANSITION_KEYS = {'id', 'version', 'frame', 'purpose', 'ownerSectionId', 'frameRange', 'neighborSectionIds',
                   'clockPolicy', 'continuity', 'timeline', 'dependencies'}


def _text(value: object) -> None:
    """Require a bounded authored assessment instead of an empty approval placeholder."""
    require(type(value) is str and 1 <= len(value.strip()) <= 2000, 'chunk decision needs authored assessment text')


def _transition(project: Path, row: dict, geometry: dict) -> None:
    """Require one exact adjacent transition owner and current evidence on both sides."""
    require(type(row) is dict and set(row) == TRANSITION_KEYS, 'invalid authored chunk transition')
    require(type(row['id']) is str and 1 <= len(row['id']) <= 128
            and type(row['version']) is int and row['version'] >= 1
            and type(row['frame']) is int, 'invalid chunk transition identity or version')
    _text(row['purpose'])
    neighbors = boundary_neighbors(geometry, row['frame'])
    owners = list(dict.fromkeys(chunk['sectionId'] for chunk in neighbors))
    require(row['neighborSectionIds'] == owners and row['ownerSectionId'] in owners,
            'transition needs one owning neighbor and all affected creative neighbors')
    span = row['frameRange']
    require(type(span) is list and len(span) == 2 and all(type(value) is int for value in span)
            and neighbors[0]['frameRange'][0] <= span[0] < row['frame'] < span[1]
            <= neighbors[1]['frameRange'][1], 'transition span must cover both sides within adjacent chunks')
    require(row['clockPolicy'] == 'absolute-no-restart', 'chunk transition must preserve the absolute motion clock')
    require(type(row['continuity']) is dict and set(row['continuity']) ==
            {'imagery', 'motion', 'layering', 'audio', 'captions'}, 'incomplete chunk continuity assessment')
    for assessment in row['continuity'].values():
        _text(assessment)
    evidence = transition_evidence(project, geometry, span)
    require(all(row[key] == value for key, value in evidence.items()), 'chunk transition source or state evidence changed')


def _assignment(row: dict, declared: dict, mapping: dict, transitions: list[dict]) -> None:
    """Match one unchanged creative assignment and every current proposed chunk exactly."""
    require(type(row) is dict and set(row) == ASSIGNMENT_KEYS, 'invalid chunk creative assignment')
    require(all(row[key] == declared[key] for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange'))
            and row['mapIdentity'] == mapping['identity'], 'chunk geometry or creative ownership changed')
    chunks = row['chunks']
    require(type(chunks) is list and len(chunks) == len(mapping['chunks']), 'chunk inventory is incomplete')
    for authored, actual in zip(chunks, mapping['chunks']):
        require(type(authored) is dict and set(authored) == {'id', 'frameRange', 'purpose'}
                and all(authored[key] == actual[key] for key in ('id', 'frameRange')), 'authored chunk geometry changed')
        _text(authored['purpose'])
    selected = [item['id'] for item in transitions if row['sectionId'] in item['neighborSectionIds']]
    require(row['transitionIds'] == selected, 'chunk assignment omits an owned or neighboring transition')


def read_chunk_contract(project: Path) -> dict | None:
    """Cold-read the optional authored contract; absence preserves the existing Long route."""
    file = project / CONTRACT
    if not file.exists():
        return None
    require(not (project / 'SHORT-PROJECT.json').exists() and file.resolve(strict=True) == file,
            'chunk contract requires a canonical Long-only project')
    value = bound_json(file)
    require(type(value) is dict and set(value) == {'schemaVersion', 'kind', 'sectionPlan', 'assignments', 'transitions'}
            and type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['kind'] == KIND, 'invalid Long chunk admission contract')
    context = read_plan(Path(value['sectionPlan']['path']))
    require(value['sectionPlan'] == context['plan'], 'chunk contract section plan changed')
    geometry = chunk_geometry(project, context)
    transitions = value['transitions']
    require(type(transitions) is list and len(transitions) <= 767
            and [row.get('frame') for row in transitions] == boundary_frames(geometry)
            and len({row.get('id') for row in transitions}) == len(transitions),
            'chunk transitions must cover each boundary once in order')
    for row in transitions:
        _transition(project, row, geometry)
    require(type(value['assignments']) is list and len(value['assignments']) == len(context['assignments']),
            'chunk contract must cover every creative assignment')
    for row, declared, mapping in zip(value['assignments'], context['assignments'], geometry['maps']):
        _assignment(row, declared, mapping, transitions)
    return {'contract': pin_file(file), 'value': value, 'context': context, 'geometry': geometry}


def scoped_chunk_inputs(project: Path, frame_range: list[int]) -> dict:
    """Project exact local decisions plus shared transition dependencies for compatibility."""
    contract = read_chunk_contract(project)
    require(contract is not None, 'missing Long chunk contract')
    return chunk_projection(contract, frame_range)


def chunk_projection(contract: dict, frame_range: list[int]) -> dict:
    """Select local technical policy; author task generations retain their separate review authority."""
    rows = [row for row in contract['value']['assignments'] if row['frameRange'][0] < frame_range[1]
            and row['frameRange'][1] > frame_range[0]]
    local = [{'sectionId': row['sectionId'], 'frameRange': row['frameRange'],
              'chunks': [chunk for chunk in row['chunks'] if chunk['frameRange'][0] < frame_range[1]
                         and chunk['frameRange'][1] > frame_range[0]]} for row in rows]
    return {'schemaVersion': 1, 'kind': KIND, 'sharedPlan': contract['context']['sharedPlan'],
            'assignments': local, 'transitions': [row for row in contract['value']['transitions']
                if row['frameRange'][0] < frame_range[1] and row['frameRange'][1] > frame_range[0]]}


def chunk_prebuild_pins(project: Path) -> dict[str, str]:
    """Include the original assignment authority and shared inputs in the prebuild digest."""
    contract = read_chunk_contract(project)
    if contract is None:
        return {}
    pins = [contract['contract'], contract['context']['plan'], contract['context']['sharedPlan']]
    pins += [pin for row in contract['context']['assignments'] for pin in row['authorBinding']['inputs']]
    return {row['path']: row['sha256'] for row in pins}


def validate_chunk_options(args: object, project: Path) -> None:
    """Require the explicit new Long workflow to supply its frozen reviewed contract."""
    enabled = bool(getattr(args, 'chunks', False))
    file = project / CONTRACT
    if not enabled and not file.exists():
        return
    parent = getattr(args, 'resume_from', None) or getattr(args, 'repair_from', None)
    require(enabled or parent, 'LONG-CHUNKS.json requires the explicit --chunks workflow')
    require(file.is_file(), '--chunks requires authored LONG-CHUNKS.json')
    contract = read_chunk_contract(project)
    plan = getattr(args, 'section_plan', None)
    require(plan is not None or getattr(args, 'resume_from', None), '--chunks requires its frozen --section-plan')
    if plan is not None:
        require(str(plan.resolve(strict=True)) == contract['context']['plan']['path'],
                '--section-plan differs from the authored chunk contract')


def require_chunk_review(project: Path, review: dict) -> None:
    """Require the existing independent prebuild judgment to explicitly reference the contract."""
    file = project / CONTRACT
    if not file.exists():
        return
    require(any(row.get('path') == str(file) and row.get('sha256') == digest(file)
                for row in review.get('evidence', [])), 'Long chunk contract needs explicit independent prebuild evidence')


def chunk_admission(contract: dict) -> dict:
    """Bind local current decisions for existing task readers after prebuild admission."""
    rows = []
    for row, mapping in zip(contract['value']['assignments'], contract['geometry']['maps']):
        transitions = [item for item in contract['value']['transitions'] if item['id'] in row['transitionIds']]
        decisions = {'assignment': row, 'transitions': transitions, 'sharedPlan': contract['context']['sharedPlan']}
        rows.append({'sectionId': row['sectionId'], 'map': mapping, 'transitions': transitions,
                     'admissionIdentity': identity(decisions)})
    return {'schemaVersion': 1, 'contract': contract['contract'], 'assignments': rows}


def bind_chunk_request(request: dict) -> dict:
    """Freeze current chunk geometry only with its existing reviewed full or scoped snapshot."""
    contract = read_chunk_contract(Path(request['project']))
    if contract is None:
        return request
    require(request.get('adapter') == 'native-long' and request.get('revision', {}).get('mode') == 'initial-long',
            'Long chunks require the initial Long section route')
    require(request.get('sectionProduction') == contract['context'],
            'Long chunk contract differs from the registered creative assignment context')
    _validate_previous(request['revision'])
    require(request.get('prebuildReview', {}).get('status') == 'recorded-independent-plan-pass'
            and request['prebuildReview'].get('scope') == ('native-long-section-snapshot' if request.get('sectionScope')
                                                          else 'native-long-full-project')
            and request['pins'].get(contract['contract']['path']) == contract['contract']['sha256'],
            'Long chunks require their current prebuild admission')
    windows = request['revision']['renderWindows']
    require([row['startFrame'] for row in windows] + [windows[-1]['endFrame']]
            == contract['geometry']['encoderBoundaries'], 'admitted encoder windows differ from frozen chunk map')
    request['sectionChunks'] = chunk_admission(contract)
    return request


def chunk_contract_changes(parent: Path, child: Path) -> tuple[list[list[int]], str | None]:
    """Invalidate changed chunk decisions and both transition sides using exact cold projections."""
    before, after = read_chunk_contract(parent), read_chunk_contract(child)
    if before is None or after is None:
        return [], 'Long chunk admission added or removed'
    if before['geometry']['canvas'] != after['geometry']['canvas']:
        return [], 'Long chunk admission clock changed'
    prior = {row['frame']: row for row in before['value']['transitions']}
    for row in after['value']['transitions']:
        old = prior.get(row['frame'])
        require(old is None or row == old or (row['id'] == old['id'] and row['version'] > old['version']),
                'changed chunk transition must preserve identity and advance its version')
    bounds = {value for contract in (before, after) for row in contract['geometry']['maps']
              for chunk in row['chunks'] for value in chunk['frameRange']}
    bounds.update(value for contract in (before, after) for row in contract['value']['transitions']
                  for value in row['frameRange'])
    values = sorted(bounds)
    ranges = [[start, end] for start, end in zip(values, values[1:])
              if chunk_projection(before, [start, end]) != chunk_projection(after, [start, end])]
    return ranges, None


def require_chunk_request(request: dict) -> None:
    """Prevent workers from omitting or substituting the frozen authored chunk admission."""
    file = Path(request['project']) / CONTRACT
    if not file.exists() and 'sectionChunks' not in request:
        return
    expected = bind_chunk_request({key: value for key, value in request.items() if key != 'sectionChunks'})
    require(request.get('sectionChunks') == expected.get('sectionChunks'), 'Long chunk worker admission changed')
