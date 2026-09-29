"""Validate ordinary edit-plan use of a checked reference style vocabulary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from graphics.reference_style_vocabulary import find_style_contender
from style_application_variation import StyleHistory, repeat_error

REPEAT_MODES = frozenset({'new', 'varied', 'signature', 'callback', 'necessary-repeat'})
RELATIONSHIP_MODES = frozenset({'coherent', 'justified-exception'})


@dataclass(frozen=True)
class VocabularyContext:
    """Exact checked-vocabulary identity supplied by the planning controller."""

    record: dict[str, Any]
    path: str
    sha256: str
    reference_id: str


def _text(value: object, label: str, maximum: int = 4000) -> str:
    """Require a bounded nonblank authored string."""
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'invalid {label}')
    return value


def _strings(value: object, label: str, maximum: int, empty: bool = False) -> list[str]:
    """Require bounded unique strings."""
    if not isinstance(value, list) or (not empty and not value) or len(value) > maximum:
        raise ValueError(f'invalid {label} count')
    result = [_text(item, label) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f'duplicate {label}')
    return result


def _keys(value: object, fields: set[str], label: str) -> dict:
    """Require one exact object contract."""
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f'invalid {label} fields')
    return value


def _families(vocabulary: dict) -> dict[str, list[str]]:
    """Project the checked vocabulary into allowed contender identities."""
    return {row['id']: [item['catalogRef'] for item in row['contenders']]
            for row in vocabulary['families']}


def _graphics(plan: dict) -> dict[str, dict]:
    """Index executable graphic entries by their controller-owned identity."""
    rows = plan.get('graphicsTrack') or []
    if not isinstance(rows, list):
        raise ValueError('graphicsTrack must be a list')
    result = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f'graphicsTrack[{index}] must be an object')
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f'graphicsTrack[{index}] needs its reconciled id before style review')
        if identifier in result:
            raise ValueError('graphicsTrack has duplicate ids')
        result[identifier] = row
    return result


def _choice(value: object) -> dict:
    """Validate one semantic choice bound to an ordinary graphic entry."""
    fields = {'graphicId', 'viewerNeed', 'familyId', 'contenderRef', 'anatomy', 'configuration',
              'development', 'consideredContenders', 'selectionReason',
              'repeatMode', 'repeatReason'}
    row = _keys(value, fields, 'ordinary style choice')
    for field in fields - {'consideredContenders'}:
        row[field] = _text(row[field], f'ordinary style {field}')
    row['consideredContenders'] = _strings(
        row['consideredContenders'], 'ordinary considered contender', 8)
    if row['repeatMode'] not in REPEAT_MODES:
        raise ValueError('invalid ordinary style repeat mode')
    return row


def _supplemental_choice(value: object) -> dict:
    """Validate one general-catalog choice outside the reference vocabulary."""
    fields = {'graphicId', 'viewerNeed', 'catalogId', 'anatomy', 'configuration',
              'development', 'selectionReason', 'relationshipMode',
              'relationshipEvidence', 'repeatMode', 'repeatReason'}
    row = _keys(value, fields, 'ordinary supplemental style choice')
    for field in fields:
        row[field] = _text(row[field], f'ordinary supplemental style {field}')
    if row['relationshipMode'] not in RELATIONSHIP_MODES:
        raise ValueError('invalid ordinary supplemental style relationship mode')
    if row['repeatMode'] not in REPEAT_MODES:
        raise ValueError('invalid ordinary supplemental style repeat mode')
    return row


def _binding(application: dict, context: VocabularyContext) -> list[str]:
    """Check exact vocabulary identity without transferring an approval claim."""
    expected = {'path': context.path, 'sha256': context.sha256,
                'referenceId': context.reference_id}
    errors = [] if application.get('vocabulary') == expected else [
        'styleApplication binds a different reference vocabulary']
    if context.record.get('referenceId') != context.reference_id:
        errors.append('reference vocabulary identity differs from selected reference')
    return errors


def _selected_contender(vocabulary: dict, row: dict) -> dict:
    """Return the exact family contender or fail without fuzzy matching."""
    contender = find_style_contender(
        vocabulary, row['familyId'], row['contenderRef'])
    if contender is not None:
        return contender
    raise ValueError(f"unknown contender {row['contenderRef']}")


def _application_choices(application: dict) -> tuple[list[dict], list[dict]]:
    """Read bounded vocabulary and supplemental choice lists."""
    raw = application.get('choices')
    supplemental_raw = application.get('supplementalChoices', [])
    if not isinstance(raw, list) or len(raw) > 512:
        raise ValueError('invalid ordinary style choices')
    if not isinstance(supplemental_raw, list) or len(supplemental_raw) > 512:
        raise ValueError('invalid ordinary supplemental style choices')
    if len(raw) + len(supplemental_raw) > 512:
        raise ValueError('ordinary style application exceeds 512 total choices')
    return ([_choice(value) for value in raw],
            [_supplemental_choice(value) for value in supplemental_raw])


def _supplemental_identity(row: dict, graphic: dict, identifier: str) -> str:
    """Bind a supplemental choice to its actual ordinary adapter identity."""
    if row['catalogId'] != graphic.get('kind'):
        raise ValueError(
            f'supplemental style choice {identifier} differs from its '
            'executable graphic kind')
    return row['catalogId']


def _vocabulary_identity(row: dict, graphic: dict, identifier: str,
                         vocabulary: dict) -> str:
    """Bind a claimed vocabulary choice to its exact ready contender."""
    families = _families(vocabulary)
    contenders, considered = families.get(row['familyId']), row['consideredContenders']
    if not contenders or row['contenderRef'] not in contenders \
            or not set(considered) <= set(contenders) \
            or row['contenderRef'] not in considered \
            or len(considered) < min(2, len(contenders)):
        raise ValueError(f'style choice {identifier} does not compare its family contenders')
    candidate = vocabulary['candidates'][row['contenderRef']]
    if candidate['record']['id'] != graphic.get('kind'):
        raise ValueError(f'style choice {identifier} differs from its executable graphic kind')
    if _selected_contender(vocabulary, row)['availability'] != 'ready':
        raise ValueError(f'style choice {identifier} selects an unavailable contender')
    return candidate['record']['id']


def _validate_choices(plan: dict, application: dict, vocabulary: dict) -> None:
    """Bind all graphics once and check repeats by actual catalog identity."""
    graphics = _graphics(plan)
    choices, supplemental = _application_choices(application)
    all_rows = choices + supplemental
    by_id = {row['graphicId']: row for row in all_rows}
    supplemental_ids = {row['graphicId'] for row in supplemental}
    if len(by_id) != len(all_rows) or set(by_id) != set(graphics):
        raise ValueError(
            'styleApplication choices and supplementalChoices must bind every '
            'graphicsTrack id exactly once')
    seen = StyleHistory()
    for identifier, graphic in graphics.items():
        row = by_id[identifier]
        identity = _supplemental_identity(row, graphic, identifier) \
            if identifier in supplemental_ids else _vocabulary_identity(
                row, graphic, identifier, vocabulary)
        if repeat_error(identity, row, seen):
            raise ValueError(f'style choice {identifier} has an inconsistent repeat mode')


def _choice_errors(plan: dict, application: dict, vocabulary: dict) -> list[str]:
    """Return one bounded error for an invalid mixed style application."""
    try:
        _validate_choices(plan, application, vocabulary)
        return []
    except (KeyError, TypeError, ValueError) as exc:
        return [str(exc)]


def lint_style_application(plan: dict[str, Any],
                           context: VocabularyContext | None) -> dict[str, Any]:
    """Return an ordinary-plan verdict without changing existing pack semantics."""
    application = plan.get('styleApplication')
    if context is None:
        errors = ['styleApplication requires a current selected reference vocabulary'] \
            if application is not None else []
        return {'ok': not errors, 'errors': errors,
                'metrics': {'styleChoices': 0, 'supplementalStyleChoices': 0,
                            'vocabularyAvailable': False}}
    errors = []
    try:
        required = {'schemaVersion', 'vocabulary', 'choices', 'limitations'}
        allowed = required | {'supplementalChoices'}
        if not isinstance(application, dict) or not required <= set(application) \
                or not set(application) <= allowed:
            raise ValueError('invalid ordinary styleApplication fields')
        if application['schemaVersion'] != 1:
            raise ValueError('unsupported ordinary styleApplication schema')
        _strings(application['limitations'], 'ordinary style limitation', 64, empty=True)
        errors += _binding(application, context)
        errors += _choice_errors(plan, application, context.record)
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
    choices = application.get('choices', []) if isinstance(application, dict) else []
    supplemental = application.get('supplementalChoices', []) \
        if isinstance(application, dict) else []
    return {'ok': not errors, 'errors': errors,
            'metrics': {'styleChoices': len(choices) if isinstance(choices, list) else 0,
                        'supplementalStyleChoices': len(supplemental)
                        if isinstance(supplemental, list) else 0,
                        'vocabularyAvailable': True}}
