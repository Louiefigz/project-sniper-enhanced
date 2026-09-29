"""Frozen logical assignments layered on the existing bounded production task authority.

Authors work in claim-owned directories before an integrated immutable project is
admitted. A plan identifies those private artifacts by relative name, and the
adapter checks their exact bytes against the integrated project before rendering.
Logical groups are independent of the encoder's small technical frame windows.
"""
from __future__ import annotations

import math
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_segments.long_plan import identity
from studio.production.section_results import canonical_path, rehash, require, validate_binding, validate_pins
from studio.production.task_schema import TASK_ID
from studio.production.tasks import TaskSpec

PLAN_KEYS = {'schemaVersion', 'kind', 'authority', 'batchId', 'clipId', 'directorTaskId',
             'deadlineElapsed', 'outputRoot', 'sharedPlan', 'assignments'}
ASSIGNMENT_KEYS = {'sectionId', 'generation', 'frameRange', 'inputs', 'projectFiles'}


def pin_file(file: Path) -> dict:
    """Capture and validate one immutable canonical artifact reference."""
    pin = {'path': str(file), 'sha256': digest(file), 'bytes': file.stat().st_size}
    rehash(pin)
    return pin


def relative_file(value: object) -> str:
    """Accept an exact portable relative artifact name, never a traversal or absolute path."""
    require(type(value) is str and bool(value) and '\\' not in value, 'invalid relative project artifact')
    file = Path(value)
    require(not file.is_absolute() and '..' not in file.parts and str(file) == value,
            'invalid relative project artifact')
    return value


def project_files(value: object) -> dict:
    """A bounded mapping from private authored artifact names to integrated project files."""
    require(type(value) is dict and 1 <= len(value) <= 32, 'assignment needs authored project files')
    for artifact, destination in value.items():
        relative_file(artifact)
        relative_file(destination)
    require(len(set(value.values())) == len(value), 'duplicate integrated project file')
    return value


def assignment(plan: dict, row: dict, plan_pin: dict, parent: dict | None = None) -> dict:
    """Freeze one shared-plan-bound author task and deterministic successor task ids."""
    require(type(row) is dict and set(row) - {'priorAuthorTaskId'} == ASSIGNMENT_KEYS, 'invalid logical assignment')
    files = project_files(row['projectFiles'])
    inputs = validate_pins(row['inputs'])
    inherited = parent['authorBinding']['inputs'] if parent else []
    pins = unique_pins([plan['sharedPlan'], plan_pin, *inputs, *inherited])
    fingerprint = identity({'sharedPlan': plan['sharedPlan'],
                            'assignment': {key: row[key] for key in ASSIGNMENT_KEYS}})
    binding = {'role': 'author', 'sectionId': row['sectionId'], 'generation': row['generation'],
               'sharedPlanSha256': plan['sharedPlan']['sha256'], 'inputIdentity': fingerprint,
               'frameRange': row['frameRange'], 'outputRoot': plan['outputRoot'],
               'authorTaskId': None, 'inputs': pins, 'mediaManifest': None}
    validate_binding(binding)
    key = identity({'plan': plan_pin, 'binding': binding})[:24]
    result = {key: binding[key] for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange')} | {
        'projectFiles': files, 'authorTaskId': f'ls-{key}-author', 'earlyTaskId': f'ls-{key}-early',
        'encodedTaskId': f'ls-{key}-encoded', 'authorBinding': binding,
        'authorKind': 'author', 'replacesAuthor': None, 'priorAuthorTaskId': row.get('priorAuthorTaskId')}
    from studio.production.section_assignment_repair import apply_parent
    return apply_parent(result, parent)


def unique_pins(pins: list[dict]) -> list[dict]:
    """Deduplicate equal references while refusing two meanings for the same path."""
    selected = {}
    for pin in pins:
        require(pin['path'] not in selected or selected[pin['path']] == pin, 'conflicting section input pins')
        selected[pin['path']] = pin
    result = [selected[key] for key in sorted(selected)]
    validate_pins(result, 1)
    for pin in result:
        rehash(pin)
    return result


def read_plan(file: Path, depth: int = 0) -> dict:
    """Read a closed immutable plan before author dispatch or project binding."""
    file = file.resolve(strict=True)
    receipt, value = pin_file(file), bound_json(file)
    require(depth <= 8, 'section plan ancestry exceeds the bounded repair lineage')
    require(type(value) is dict and set(value) - {'parentPlan'} == PLAN_KEYS and type(value['schemaVersion']) is int
            and value['schemaVersion'] == 1 and value['kind'] == 'native-long-section-assignments',
            'invalid section assignment plan')
    for key in ('batchId', 'clipId', 'directorTaskId'):
        require(type(value[key]) is str and TASK_ID.fullmatch(value[key]) is not None, 'invalid section authority id')
    for key in ('authority', 'outputRoot'):
        path = canonical_path(value[key])
        require(path.resolve() == path, 'section authority or output path contains a link')
    deadline = value['deadlineElapsed']
    require(type(deadline) in (int, float) and math.isfinite(deadline) and deadline > 0,
            'invalid section deadline')
    rehash(value['sharedPlan'])
    rows = value['assignments']
    require(type(rows) is list and 1 <= len(rows) <= 3, 'one to three logical assignments required')
    parent = parent_plan(value, depth)
    assignments = [assignment(value, row, receipt, parent.get(row['sectionId'])) for row in rows]
    require(not parent or set(parent) == {row['sectionId'] for row in rows}, 'section repair changed its assignments')
    require(len({row['sectionId'] for row in assignments}) == len(rows), 'duplicate logical section')
    bounds = [row['frameRange'] for row in assignments]
    require(bounds[0][0] == 0 and all(left[1] == right[0] for left, right in zip(bounds, bounds[1:])),
            'logical sections must cover one contiguous absolute frame clock')
    destinations = [name for row in assignments for name in row['projectFiles'].values()]
    require(len(destinations) == len(set(destinations)), 'authors overlap integrated project files')
    return {key: value[key] for key in set(value) - {'kind', 'assignments'}} | {
        'plan': receipt, 'assignments': assignments}


def parent_plan(value: dict, depth: int) -> dict:
    """Require the same authority, immutable creative plan and private output namespace across repair."""
    pin = value.get('parentPlan')
    if pin is None:
        return {}
    rehash(pin)
    parent = read_plan(Path(pin['path']), depth + 1)
    keys = ('authority', 'batchId', 'clipId', 'directorTaskId', 'outputRoot', 'sharedPlan', 'deadlineElapsed')
    require(all(value[key] == parent[key] for key in keys), 'section repair changed its shared plan or authority')
    return {row['sectionId']: row for row in parent['assignments']}


def task_spec(context: dict, row: dict, binding: dict) -> TaskSpec:
    """Declare ordinary author or dependent review work; all existing caps and claims remain authoritative."""
    role = binding['role']
    task_id = row[{'author': 'authorTaskId', 'early-review': 'earlyTaskId',
                   'encoded-review': 'encodedTaskId'}[role]]
    prerequisites = () if role == 'author' else (row['authorTaskId'],)
    if role == 'encoded-review':
        prerequisites += (row['earlyTaskId'],)
    return TaskSpec(task_id=task_id, run_id=context['batchId'], kind=row['authorKind'] if role == 'author' else 'review',
                    version=f"section-{identity(binding)[:24]}-g{row['generation']}",
                    input_fingerprint=identity(binding), deadline_elapsed=context['deadlineElapsed'],
                    clip_id=context['clipId'], parent=context['directorTaskId'], prerequisites=prerequisites,
                    section_binding=binding, replaces=row['replacesAuthor'] if role == 'author' else None)


def require_context(record: dict, context: dict) -> None:
    """Require an enrolled director and the same authorized Long output."""
    director = record['production']['tasks'].get(context['directorTaskId'])
    require(record['batchId'] == context['batchId'] and director is not None
            and director['kind'] == 'director' and director['state'] == 'running'
            and director.get('handle', {}).get('type') == 'host', 'section work needs its enrolled live director')
    clip = record['clips'].get(context['clipId'])
    require(clip is not None and clip.get('output', {}).get('format') == 'long',
            'section tasks require an authorized Long output')


def revalidate_context(request: dict) -> dict:
    """Reconstruct the frozen assignment authority instead of trusting mutable request fields."""
    context = request['sectionProduction']
    rehash(context['plan'])
    require(request['pins'].get(context['plan']['path']) == context['plan']['sha256'], 'assignment plan is not admitted')
    require(read_plan(Path(context['plan']['path'])) == context, 'section production plan changed')
    budget = request.get('productionBudget')
    require(budget is not None and all(context[key] == budget[key] for key in ('authority', 'batchId', 'clipId')),
            'section tasks and export must share the same production authority')
    for row in context['assignments']:
        for pin in row['authorBinding']['inputs']:
            require(request['pins'].get(pin['path']) == pin['sha256'], 'section plan input is not admitted')
    return context
