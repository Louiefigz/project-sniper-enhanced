"""Validate evidence-bound style choices in authored native Long projects."""
from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from cut_preview_io import bound_json, file_hash, read_bytes
from graphics.catalog_discovery import load_catalog
from graphics.reference_style_vocabulary import find_style_contender, read_checked_vocabulary
from studio.native_stage_evidence import require
from style_application_variation import assert_style_variation

MAX_TEXT = 4_000
REPEAT_MODES = frozenset({'new', 'varied', 'signature', 'callback', 'necessary-repeat'})
MAX_SELECTED_INPUT_BYTES = 128 * 1024 ** 3
MAX_IMPLEMENTATION_BYTES = 16 * 1024 ** 3


@dataclass(frozen=True)
class ChoiceContext:
    """Long-project evidence needed to validate one authored choice inventory."""

    plan: dict
    application: dict
    vocabulary: dict
    bindings: dict[str, set[str]]
    supplemental: dict[str, set[str]]
    html: str

def _text(value: object, label: str, maximum: int = MAX_TEXT) -> str:
    """Require one bounded authored string."""
    require(isinstance(value, str) and 0 < len(value) <= maximum
            and not any(char in value for char in '\0\r'), f'invalid {label}')
    return value

def _list(value: object, label: str, maximum: int, empty: bool = False) -> list[str]:
    """Require bounded unique strings."""
    require(isinstance(value, list) and (empty or value) and len(value) <= maximum,
            f'invalid {label} count')
    result = [_text(item, label) for item in value]
    require(len(result) == len(set(result)), f'duplicate {label}')
    return result

def _keys(value: object, fields: set[str], label: str) -> dict:
    """Require one exact object contract."""
    require(isinstance(value, dict) and set(value) == fields, f'invalid {label} fields')
    return value

def _request(plan: dict) -> tuple[Path, dict, dict[str, str]] | None:
    """Read the exact prepared request and selected-reference evidence."""
    ref = plan.get('requestPacket')
    if ref is None:
        return None
    ref = _keys(ref, {'path', 'sha256'}, 'long request binding')
    file = Path(_text(ref['path'], 'long request path'))
    require(file.is_absolute() and file.resolve(strict=True) == file,
            'long request path must be canonical')
    expected = _text(ref['sha256'], 'long request hash', 64)
    packet = bound_json(file, expected)
    pins = {str(file): expected}
    selected = packet.get('selectedReferences', [])
    require(isinstance(selected, list) and len(selected) <= 10_000,
            'invalid selected-reference pins')
    for row in selected:
        row = _keys(row, {'path', 'sha256'}, 'selected-reference pin')
        source = Path(_text(row['path'], 'selected-reference path'))
        sha256 = _text(row['sha256'], 'selected-reference hash', 64)
        require(source.is_absolute() and source.resolve(strict=True) == source
                and file_hash(source, MAX_SELECTED_INPUT_BYTES) == sha256,
                'selected-reference evidence changed')
        require(str(source) not in pins or pins[str(source)] == sha256,
                'conflicting selected-reference pins')
        pins[str(source)] = sha256
    return file, packet, pins

def _vocabulary(request: tuple[Path, dict, dict[str, str]]) -> dict | None:
    """Load the current checked vocabulary declared by the prepared request."""
    file, packet, _pins = request
    selected = packet.get('selectedReference')
    if selected is None:
        return None
    require(isinstance(selected, dict), 'invalid selected reference summary')
    if selected.get('styleVocabularyAvailable') is not True:
        return None
    vocabulary = file.parent / 'SELECTED-REFERENCE-VOCABULARY.json'
    snapshot = read_checked_vocabulary(vocabulary, load_catalog())
    require(snapshot['record']['referenceId'] == selected.get('id'),
            'style vocabulary belongs to a different selected reference')
    return snapshot

def _families(vocabulary: dict) -> dict[str, list[str]]:
    """Project vocabulary families into their inspected contender identities."""
    return {family['id']: [row['catalogRef'] for row in family['contenders']]
            for family in vocabulary['families']}

def _contender(vocabulary: dict, family_id: str, contender_ref: str) -> dict:
    """Return one exact authored contender without fuzzy family fallback."""
    contender = find_style_contender(vocabulary, family_id, contender_ref)
    if contender is not None:
        return contender
    raise ValueError('long style choice names an unknown family contender')

def _mounted_on_visible_id(html: str, files: list[str], visible_ids: list[str]) -> bool:
    """Require selected project adaptations on elements owned by this scene choice."""
    tags = re.findall(r'<[^>]{1,8192}>', html)
    return all(any(f'id="{identifier}"' in tag and f'data-composition-src="{file}"' in tag
                   for identifier in visible_ids for tag in tags) for file in files)

def _catalog_bindings(project: Path, application: dict, vocabulary: dict,
                      html: str) -> dict[str, set[str]]:
    """Bind selected contenders to immutable mounted project implementations."""
    fields = {'contenderRef', 'file', 'implementationSha256', 'sourceSha256'}
    raw = application['catalogBindings']
    require(isinstance(raw, list) and len(raw) <= 128, 'invalid style catalog bindings')
    result: dict[str, set[str]] = {}
    for value in raw:
        row = _keys(value, fields, 'style catalog binding')
        contender = _text(row['contenderRef'], 'bound contender', 256)
        require(contender in vocabulary['candidates'], 'style binding names an unknown contender')
        relative = _text(row['file'], 'style implementation file', 512)
        require(re.fullmatch(r'(?:compositions|assets)/[A-Za-z0-9][A-Za-z0-9_.\-/]*', relative)
                and '..' not in Path(relative).parts, 'invalid style implementation path')
        file = project / relative
        require(file.resolve(strict=True) == file
                and file_hash(file, MAX_IMPLEMENTATION_BYTES) == row['implementationSha256'],
                'style implementation changed')
        source = vocabulary['candidates'][contender]['source']
        require(source.get('sha256') == row['sourceSha256'], 'style catalog source changed')
        require(f'data-composition-src="{relative}"' in html,
                'style implementation is not mounted in executable HTML')
        result.setdefault(contender, set()).add(relative)
    return result

def _supplemental_bindings(project: Path, application: dict,
                           html: str) -> dict[str, set[str]]:
    """Bind full-catalog native adaptations without claiming vocabulary membership."""
    fields = {'catalogRef', 'file', 'implementationSha256', 'sourceSha256'}
    raw = application.get('supplementalBindings', [])
    require(isinstance(raw, list) and len(raw) <= 128,
            'invalid supplemental catalog bindings')
    catalog = {row['ref']: row for row in load_catalog().records}
    result: dict[str, set[str]] = {}
    for value in raw:
        row = _keys(value, fields, 'supplemental catalog binding')
        ref = _text(row['catalogRef'], 'supplemental catalog ref', 256)
        record = catalog.get(ref)
        require(record is not None and record['source']['exists'],
                'supplemental binding names an unavailable catalog source')
        eligibility = record.get('eligibility') or {}
        require(eligibility.get('selectionEligible') is True
                and not str(eligibility.get('executionStatus', '')).startswith('blocked-'),
                'supplemental binding is blocked by catalog execution status')
        relative = _text(row['file'], 'supplemental implementation file', 512)
        require(re.fullmatch(r'(?:compositions|assets)/[A-Za-z0-9][A-Za-z0-9_.\-/]*', relative)
                and '..' not in Path(relative).parts, 'invalid supplemental implementation path')
        file = project / relative
        require(file.resolve(strict=True) == file
                and file_hash(file, MAX_IMPLEMENTATION_BYTES) == row['implementationSha256'],
                'supplemental implementation changed')
        source = Path(record['source']['path'])
        require(file_hash(source, MAX_IMPLEMENTATION_BYTES) == row['sourceSha256'],
                'supplemental catalog source changed')
        require(f'data-composition-src="{relative}"' in html,
                'supplemental implementation is not mounted in executable HTML')
        result.setdefault(ref, set()).add(relative)
    return result

def _choice(value: object) -> dict:
    """Validate one authored Long scene choice."""
    fields = {'choiceId', 'sceneIndex', 'viewerNeed', 'familyId', 'contenderRef', 'anatomy', 'configuration',
              'development', 'catalogFiles', 'visibleIds', 'consideredContenders',
              'selectionReason', 'repeatMode', 'repeatReason'}
    row = _keys(value, fields, 'long style choice')
    require(type(row['sceneIndex']) is int and row['sceneIndex'] >= 0,
            'invalid long style scene index')
    for field in ('choiceId', 'viewerNeed', 'familyId', 'contenderRef', 'anatomy', 'configuration',
                  'development', 'selectionReason', 'repeatReason'):
        row[field] = _text(row[field], f'long style {field}')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', row['choiceId']) is not None,
            'invalid long style choice id')
    row['catalogFiles'] = _list(row['catalogFiles'], 'long style catalog file', 16)
    row['visibleIds'] = _list(row['visibleIds'], 'long style visible id', 64)
    row['consideredContenders'] = _list(
        row['consideredContenders'], 'long considered contender', 8)
    require(row['repeatMode'] in REPEAT_MODES, 'invalid long style repeat mode')
    return row

def _supplemental_choice(value: object) -> dict:
    """Validate one style-related native choice outside the analyzed vocabulary."""
    fields = {'choiceId', 'sceneIndex', 'viewerNeed', 'catalogRef', 'anatomy',
              'configuration', 'development', 'catalogFiles', 'visibleIds',
              'selectionReason', 'relationshipMode', 'relationshipEvidence',
              'repeatMode', 'repeatReason'}
    row = _keys(value, fields, 'long supplemental style choice')
    require(type(row['sceneIndex']) is int and row['sceneIndex'] >= 0,
            'invalid long supplemental scene index')
    for field in fields - {'sceneIndex', 'catalogFiles', 'visibleIds'}:
        row[field] = _text(row[field], f'long supplemental {field}')
    row['catalogFiles'] = _list(row['catalogFiles'], 'supplemental catalog file', 16)
    row['visibleIds'] = _list(row['visibleIds'], 'supplemental visible id', 64)
    require(row['relationshipMode'] in {'coherent', 'justified-exception'},
            'invalid supplemental relationship mode')
    require(row['repeatMode'] in REPEAT_MODES, 'invalid supplemental repeat mode')
    return row

def _assert_choices(context: ChoiceContext) -> list[dict]:
    """Check content-fit comparison, executable IDs and deliberate repetition."""
    raw = context.application['choices']
    require(isinstance(raw, list) and len(raw) <= 256, 'invalid long style choices')
    choices = [_choice(row) for row in raw]
    families = _families(context.vocabulary)
    require(len({row['choiceId'] for row in choices}) == len(choices),
            'duplicate long style choice id')
    html_ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', context.html))
    for row in choices:
        require(row['sceneIndex'] < len(context.plan['scenes']),
                'long style choice names an absent scene')
        contenders = families.get(row['familyId'])
        compared = row['consideredContenders']
        require(contenders and row['contenderRef'] in contenders
                and set(compared) <= set(contenders) and row['contenderRef'] in compared
                and len(compared) >= min(2, len(contenders)),
                'long style choice does not compare its family contenders')
        require(_contender(context.vocabulary, row['familyId'],
                           row['contenderRef'])['availability'] == 'ready',
                'long style choice selects a contender that is not ready')
        require(set(row['catalogFiles']) <= context.bindings.get(row['contenderRef'], set()),
                'long style choice is not bound to its catalog implementation')
        require(set(row['visibleIds']) <= html_ids,
                'long style choice names a visual absent from executable HTML')
        require(_mounted_on_visible_id(context.html, row['catalogFiles'], row['visibleIds']),
                'long style catalog treatment is not mounted on a scene-visible element')
    expected = {(contender, file) for contender, files in context.bindings.items()
                for file in files}
    covered = {(row['contenderRef'], file) for row in choices for file in row['catalogFiles']}
    require(covered == expected, 'long style choices and catalog bindings differ')
    return choices

def _assert_supplemental(context: ChoiceContext) -> list[dict]:
    """Validate style relationships and executable evidence outside the vocabulary."""
    raw = context.application.get('supplementalChoices', [])
    require(isinstance(raw, list) and len(raw) <= 256,
            'invalid long supplemental style choices')
    choices = [_supplemental_choice(row) for row in raw]
    html_ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', context.html))
    for row in choices:
        require(row['sceneIndex'] < len(context.plan['scenes']),
                'supplemental style choice names an absent scene')
        require(set(row['catalogFiles']) <= context.supplemental.get(row['catalogRef'], set()),
                'supplemental choice is not bound to its catalog implementation')
        require(set(row['visibleIds']) <= html_ids,
                'supplemental choice names a visual absent from executable HTML')
        require(_mounted_on_visible_id(context.html, row['catalogFiles'], row['visibleIds']),
                'supplemental treatment is not mounted on a scene-visible element')
    expected = {(ref, file) for ref, files in context.supplemental.items() for file in files}
    covered = {(row['catalogRef'], file) for row in choices for file in row['catalogFiles']}
    require(covered == expected, 'supplemental choices and catalog bindings differ')
    return choices

def validate_long_style_application(project: Path, plan: dict) -> dict[str, str]:
    """Require a current application exactly when a Long request has a vocabulary."""
    request, application = _request(plan), plan.get('styleApplication')
    if request is None:
        require(application is None, 'long style application requires a prepared request')
        return {}
    vocabulary = _vocabulary(request)
    if vocabulary is None:
        require(application is None, 'long style application claims an absent vocabulary')
        return request[2]
    require(application is not None, 'vocabulary-enabled Long request requires a style application')
    required = {'schemaVersion', 'vocabulary', 'catalogBindings', 'choices', 'limitations'}
    optional = {'supplementalBindings', 'supplementalChoices'}
    require(isinstance(application, dict) and required <= set(application)
            and set(application) <= required | optional, 'invalid long style application fields')
    require(application['schemaVersion'] == 1, 'unsupported long style application')
    binding = _keys(application['vocabulary'], {'path', 'sha256', 'referenceId'},
                    'long vocabulary binding')
    require(binding == {key: vocabulary[key] for key in ('path', 'sha256')}
            | {'referenceId': vocabulary['record']['referenceId']},
            'long style application binds a different vocabulary')
    application['limitations'] = _list(
        application['limitations'], 'long style limitation', 64, empty=True)
    html = read_bytes(project / 'index.html').decode('utf-8')
    bindings = _catalog_bindings(project, application, vocabulary['record'], html)
    supplemental = _supplemental_bindings(project, application, html)
    context = ChoiceContext(plan, application, vocabulary['record'], bindings, supplemental, html)
    choices = _assert_choices(context)
    extra = _assert_supplemental(context)
    require(len(choices) + len(extra) <= 256, 'long style application exceeds 256 choices')
    assert_style_variation([(vocabulary['record']['candidates'][row['contenderRef']]
                             ['record']['id'], row) for row in choices]
                           + [(row['catalogRef'].split(':', 1)[-1], row) for row in extra])
    require(len({row['choiceId'] for row in choices + extra}) == len(choices) + len(extra),
            'duplicate long style choice id')
    return request[2]
