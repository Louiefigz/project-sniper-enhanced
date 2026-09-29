"""Prove that a native Long project executes every allocated visual decision."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import re
from pathlib import Path

from studio.native_stage_evidence import require
from studio.native_visual_plan import bound_long_visual_plan
from studio.native_visual_execution_binding import validate_execution_binding

_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
_FILE = re.compile(r'^compositions/[A-Za-z0-9][A-Za-z0-9._/-]{0,240}$')
_SHA = re.compile(r'^[a-f0-9]{64}$')
_TAG = re.compile(r'<[^>]+\bid="([^"]+)"[^>]*>', re.I)
_MAX_HTML_BYTES = 4 * 1024 * 1024


def _require_keys(row: object, keys: set[str], name: str) -> dict:
    """Require one closed object shape."""
    require(isinstance(row, dict) and set(row) == keys,
            f'{name} has unknown or missing fields')
    return row


def _ids(value: object, maximum: int, name: str) -> list[str]:
    """Require bounded, unique stable IDs."""
    require(isinstance(value, list) and len(value) <= maximum
            and len(value) == len(set(value))
            and all(isinstance(item, str) and _ID.fullmatch(item) for item in value),
            f'{name} must contain bounded unique stable IDs')
    return value


def _scene_indexes(value: object, scenes: list[dict], timing: dict) -> list[int]:
    """Bind a decision to every exact Long scene it overlaps."""
    expected = [index for index, scene in enumerate(scenes)
                if scene['startFrame'] < timing['endFrameExclusive']
                and scene['endFrame'] > timing['startFrame']]
    require(isinstance(value, list) and value == expected and bool(expected)
            and all(type(item) is int for item in value),
            'visual-plan application does not bind the exact overlapping scenes')
    return value


def _sha256(file: Path) -> str:
    """Hash one already bounded project-owned implementation."""
    digest = hashlib.sha256()
    with file.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _project_html(project: Path) -> str:
    """Read the executable entry through a fixed planning-memory boundary."""
    file = project / 'index.html'
    require(file.is_file() and not file.is_symlink()
            and file.resolve(strict=True).is_relative_to(project)
            and file.stat().st_size <= _MAX_HTML_BYTES,
            'native Long HTML is missing or exceeds the planning read bound')
    return file.read_bytes().decode('utf-8')


def _mounted(html: str, mount_id: str, relative: str) -> bool:
    """Return whether one element owns the claimed catalog mount."""
    return any(f'id="{mount_id}"' in tag
               and f'data-composition-src="{relative}"' in tag
               for tag in re.findall(r'<[^>]+>', html))


def _catalog_bindings(context: dict, value: object, candidate: dict,
                      visible_ids: list[str]) -> None:
    """Tie catalog winners to exact mounted project adaptations."""
    require(isinstance(value, list) and len(value) <= 8,
            'visual-plan catalog bindings are invalid')
    if candidate['modality'] != 'catalog':
        require(not value, 'non-catalog visual-plan choice claims catalog execution')
        return
    source = candidate.get('source') or {}
    require(value and source.get('recordId') and source.get('sourceSha256'),
            'catalog visual-plan choice lacks exact source evidence')
    fields = {'file', 'mountId', 'catalogId', 'sourceSha256',
              'implementationSha256'}
    for raw in value:
        row = _require_keys(raw, fields, 'visual-plan catalog binding')
        relative = row['file']
        mount_id = row['mountId']
        require(isinstance(relative, str) and _FILE.fullmatch(relative)
                and isinstance(mount_id, str) and _ID.fullmatch(mount_id)
                and mount_id in visible_ids
                and _mounted(context['html'], mount_id, relative)
                and row['catalogId'] == source['recordId']
                and row['sourceSha256'] == source['sourceSha256']
                and isinstance(row['implementationSha256'], str)
                and _SHA.fullmatch(row['implementationSha256']),
                'visual-plan catalog binding differs from its selected candidate')
        file = context['project'] / relative
        require(file.is_file() and not file.is_symlink()
                and file.resolve(strict=True).is_relative_to(context['project'])
                and _sha256(file) == row['implementationSha256'],
                'visual-plan catalog implementation is missing or changed')
        admission = candidate.get('catalogAdmission') or {}
        require(admission.get('executionStatus') != 'reference'
                or row['implementationSha256'] != source['sourceSha256'],
                'reference catalog choice requires a project-owned adaptation')
        require(f'data-composition-src="{relative}"' in context['html'],
                'visual-plan catalog implementation is not mounted')


def _visible_ids(value: object, candidate: dict, html: str) -> list[str]:
    """Require actual executable IDs for every rendered allocation."""
    ids = _ids(value, 64, 'visual-plan application visible IDs')
    require((candidate['modality'] == 'omit') == (not ids),
            'visual-plan application needs IDs for every rendered choice')
    executable = {match.group(1) for match in _TAG.finditer(html)}
    require(all(identifier in executable for identifier in ids),
            'visual-plan application names an absent executable visual')
    return ids


def _timed_visible_ids(context: dict, ids: list[str], timing: dict) -> None:
    """Require each claimed visual element to execute on the planned frame window."""
    if not ids or context['plan'].get('schemaVersion') != 2:
        return
    rate = context['plan']['canvas']['frameRate']
    numerator, denominator = (int(item) for item in rate.split('/'))
    fps = Fraction(numerator, denominator)
    tags = re.findall(r'<[^>]+>', context['html'])
    for identifier in ids:
        tag = next((item for item in tags if f'id="{identifier}"' in item), '')
        start = re.search(r'\bdata-start="([^"]+)"', tag)
        duration = re.search(r'\bdata-duration="([^"]+)"', tag)
        require(start is not None and duration is not None
                and Fraction(start.group(1)) * fps == timing['startFrame']
                and (Fraction(start.group(1)) + Fraction(duration.group(1))) * fps
                    == timing['endFrameExclusive'],
                'visual-plan executable timing differs from its opportunity')


def _scene_visual_ownership(context: dict, decisions: list[dict]) -> None:
    """Bind every current visual ID to the exact Long scenes that execute it."""
    if context['plan'].get('schemaVersion') != 2:
        return
    expected: list[list[str]] = [[] for _scene in context['scenes']]
    for decision in decisions:
        for scene_index in decision['sceneIndexes']:
            expected[scene_index].extend(identifier for identifier in decision['visibleIds']
                                         if identifier not in expected[scene_index])
    for scene, identifiers in zip(context['scenes'], expected):
        scope = context.get('sectionScope')
        if scope and (scene['endFrame'] <= scope['frameRange'][0] or scene['startFrame'] >= scope['frameRange'][1]):
            continue
        require(scene.get('visualIds') == identifiers,
                'Long scene visual ownership differs from visual-plan execution')


def _style_coherence(context: dict, item: dict) -> None:
    """Keep style-family composition prose equal to the allocated candidate."""
    application = context['plan'].get('styleApplication') or {}
    choices = [*(application.get('choices') or []),
               *(application.get('supplementalChoices') or [])]
    for choice in choices:
        overlaps = (isinstance(choice, dict)
                    and choice.get('sceneIndex') in item['sceneIndexes']
                    and isinstance(choice.get('visibleIds'), list)
                    and set(choice['visibleIds']) & set(item['visibleIds']))
        require(not overlaps or (choice.get('anatomy') == item['anatomy']
                and choice.get('development') == item['development']),
                'visual-plan execution and style application disagree on composition development')


def _validate_decision(context: dict, row: object, allocation: dict) -> None:
    """Validate one exact opportunity/candidate/timing execution row."""
    fields = {'opportunityId', 'candidateId', 'anatomy', 'development',
              'startFrame', 'endFrameExclusive', 'sceneIndexes', 'visibleIds',
              'catalogBindings', 'binding'}
    item = _require_keys(row, fields, 'visual-plan application decision')
    opportunity = context['opportunities'].get(allocation['opportunityId'])
    candidate = next((candidate for candidate in opportunity['candidates']
                      if candidate['id'] == allocation['candidateId']), None) \
        if opportunity else None
    require(candidate is not None
            and item['opportunityId'] == opportunity['id']
            and item['candidateId'] == candidate['id']
            and item['anatomy'] == candidate['composition']['anatomy']
            and item['development'] == candidate['composition']['development'],
            'visual-plan application differs from its allocation')
    timing = opportunity['timing']
    require(item['startFrame'] == timing['startFrame']
            and item['endFrameExclusive'] == timing['endFrameExclusive'],
            'visual-plan application timing differs from its opportunity')
    _scene_indexes(item['sceneIndexes'], context['scenes'], timing)
    visible_ids = _visible_ids(item['visibleIds'], candidate, context['html'])
    require(not set(visible_ids) & context['seen'],
            'visual-plan application duplicates executable visual ownership')
    context['seen'].update(visible_ids)
    _timed_visible_ids(context, visible_ids, timing)
    _catalog_bindings(context, item['catalogBindings'], candidate,
                      item['visibleIds'])
    validate_execution_binding({**context, 'timing': timing}, item,
                               candidate, visible_ids)
    _style_coherence(context, item)


def validate_long_visual_plan_application(project: Path, plan: dict, section_scope: dict | None = None) -> dict[str, str]:
    """Validate complete allocation-to-executable coverage for native Long."""
    visual_plan, pins = bound_long_visual_plan(project, plan)
    application = plan.get('visualPlanApplication')
    if visual_plan is None:
        require(application is None,
                'visual-plan application lacks its planning authority')
        return pins
    require(application is not None,
            'allocated visual plan requires an execution application')
    fields = {'schemaVersion', 'route', 'visualPlanSha256', 'decisions'}
    application = _require_keys(application, fields,
                                'native visual-plan application')
    binding = plan['visualPlan']
    require(application['schemaVersion'] == 1
            and application['route'] == 'native-long'
            and application['visualPlanSha256'] == binding['visualPlanSha256'],
            'native visual-plan application differs from its authority')
    decisions = application['decisions']
    allocated = scoped_allocations(visual_plan, section_scope)
    require(isinstance(decisions, list) and len(decisions) == len(allocated),
            'visual-plan application must cover every allocation exactly once')
    context = {'project': project, 'plan': plan, 'scenes': plan['scenes'],
               'html': _project_html(project), 'sectionScope': section_scope,
               'seen': set(),
               'opportunities': {row['id']: row
                                 for row in visual_plan['opportunities']}}
    for row, allocation in zip(decisions, allocated):
        _validate_decision(context, row, allocation)
    _scene_visual_ownership(context, decisions)
    return pins


def scoped_allocations(visual_plan: dict, section_scope: dict | None) -> list[dict]:
    """Keep full frozen planning authority while admitting exactly one complete owned range."""
    allocated = visual_plan['allocation']['decisions']
    if section_scope is None:
        return allocated
    start, end = section_scope['frameRange']
    opportunities = {row['id']: row for row in visual_plan['opportunities']}
    selected = []
    for allocation in allocated:
        timing = opportunities[allocation['opportunityId']]['timing']
        left, right = timing['startFrame'], timing['endFrameExclusive']
        if right <= start or left >= end:
            continue
        require(start <= left < right <= end, 'section scope cuts through a visual allocation; widen or refuse')
        selected.append(allocation)
    return selected
