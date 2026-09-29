"""Derive strict native modality evidence from executable HTML and local assets."""
from __future__ import annotations

from fractions import Fraction
import hashlib
from html import unescape
from pathlib import Path, PurePosixPath
import re

from studio.native_stage_evidence import require

_TAG = re.compile(r'<([A-Za-z][A-Za-z0-9-]*)\b[^>]*>')


def _attribute(tag: str, name: str) -> str | None:
    matches = re.findall(rf'\s{re.escape(name)}="([^"]*)"', tag)
    require(len(matches) <= 1, f'native element duplicates {name}')
    return matches[0] if matches else None


def _element(html: str, identifier: str) -> dict:
    matches = [match for match in _TAG.finditer(html)
               if _attribute(match.group(0), 'id') == identifier]
    require(len(matches) == 1, 'native execution element is absent or duplicated')
    match = matches[0]
    tag_name, opening = match.group(1), match.group(0)
    closing = f'</{tag_name}>'
    end = html.find(closing, match.end())
    markup = opening if end < 0 else html[match.start():end + len(closing)]
    return {'tagName': tag_name, 'opening': opening, 'markup': markup}


def _fps(context: dict) -> Fraction:
    value = context['plan']['canvas']['frameRate']
    numerator, denominator = (int(item) for item in value.split('/'))
    rate = Fraction(numerator, denominator)
    require(rate > 0, 'native visual plan has no exact frame rate')
    return rate


def _range(item: dict, context: dict, media: bool = False) -> dict:
    start_name = 'data-media-start' if media else 'data-start'
    raw_start = _attribute(item['opening'], start_name) or '0'
    raw_duration = _attribute(item['opening'], 'data-duration')
    try:
        start, duration = Fraction(raw_start), Fraction(raw_duration or '')
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('native execution element lacks an exact static range') from exc
    first, last = start * _fps(context), (start + duration) * _fps(context)
    require(start >= 0 and duration > 0
            and first.denominator == last.denominator == 1,
            'native execution element range is not frame-exact')
    return {'startFrame': int(first), 'endFrameExclusive': int(last)}


def _one(context: dict, visible_ids: list[str]) -> dict:
    require(len(visible_ids) == 1,
            'native modality requires one exact executable element')
    item = _element(context['html'], visible_ids[0])
    require(_range(item, context) == context['timing'],
            'native execution element timing differs from its opportunity')
    return item


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _text(context: dict, visible_ids: list[str]) -> dict:
    item = _one(context, visible_ids)
    text = re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ',
                                               item['markup']))).strip()
    require(text and item['tagName'] not in {'video', 'audio'}
            and _attribute(item['opening'], 'data-composition-src') is None
            and _attribute(item['opening'], 'data-transition-kind') is None,
            'native text binding does not name exact visible text')
    return {'kind': 'text', 'elementId': visible_ids[0],
            'outputRange': context['timing'], 'visibleText': text,
            'contentSha256': _sha(item['markup'])}


def _transition(context: dict, visible_ids: list[str]) -> dict:
    item = _one(context, visible_ids)
    mechanism = _attribute(item['opening'], 'data-transition-kind')
    require(bool(mechanism), 'native transition binding lacks an executed mechanism')
    return {'kind': 'transition', 'elementId': visible_ids[0],
            'outputRange': context['timing'], 'mechanism': mechanism,
            'configurationSha256': _sha(item['markup'])}


def _asset(context: dict, item: dict) -> tuple[str, str]:
    relative = _attribute(item['opening'], 'src')
    require(isinstance(relative, str) and relative.startswith('assets/')
            and '..' not in PurePosixPath(relative).parts,
            'native media binding names an invalid local asset')
    file = context['project'] / relative
    require(file.is_file() and not file.is_symlink()
            and file.resolve(strict=True).is_relative_to(context['project']),
            'native media binding names an unadmitted staged asset')
    digest = hashlib.sha256()
    with file.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return relative, digest.hexdigest()


def _media(context: dict, candidate: dict,
           visible_ids: list[str], presenter: bool) -> dict:
    item = _one(context, visible_ids)
    require(item['tagName'] == 'video',
            'native media binding must name one executed video element')
    asset_file, digest = _asset(context, item)
    common = {'elementId': visible_ids[0], 'assetFile': asset_file,
              'sourceSha256': digest, 'sourceRange': _range(item, context, True),
              'outputRange': context['timing'],
              'elementSha256': _sha(item['markup'])}
    if presenter:
        return {'kind': 'presenter', **common}
    source = candidate.get('source') or {}
    expected_sha = source.get('sourceSha256', source.get('sha256'))
    require(source.get('recordId') and expected_sha == digest
            and source.get('range') == common['sourceRange'],
            'native media execution differs from its admitted candidate source')
    return {'kind': 'media', 'sourceRecordId': source['recordId'], **common}


def _custom(context: dict, visible_ids: list[str]) -> dict:
    require(bool(visible_ids), 'custom-native execution has no visible IDs')
    for identifier in visible_ids:
        require(_range(_element(context['html'], identifier), context)
                == context['timing'],
                'custom-native element timing differs from its opportunity')
    return {'kind': 'custom-native', 'visibleIds': visible_ids,
            'implementationSha256': _sha(context['html']),
            'outputRange': context['timing']}


def _catalog(context: dict, item: dict, visible_ids: list[str]) -> dict:
    mounts = item['catalogBindings']
    require([row['mountId'] for row in mounts] == visible_ids,
            'native catalog binding does not own the exact mounted IDs')
    for identifier in visible_ids:
        require(_range(_element(context['html'], identifier), context)
                == context['timing'],
                'native catalog mount timing differs from its opportunity')
    return {'kind': 'catalog', 'mounts': mounts}


def _expected(context: dict, item: dict,
              candidate: dict, visible_ids: list[str]) -> dict:
    modality = candidate['modality']
    if modality == 'catalog':
        return _catalog(context, item, visible_ids)
    if modality == 'text':
        return _text(context, visible_ids)
    if modality == 'transition':
        return _transition(context, visible_ids)
    if modality == 'custom-native':
        return _custom(context, visible_ids)
    if modality == 'presenter':
        return _media(context, candidate, visible_ids, True)
    if modality in {'source-footage', 'supplied-broll', 'external-media'}:
        return _media(context, candidate, visible_ids, False)
    require(modality == 'omit', 'native execution modality is unsupported')
    return {'kind': 'omit'}


def validate_execution_binding(context: dict, item: dict,
                               candidate: dict, visible_ids: list[str]) -> None:
    """Reject any authored binding unequal to executable native project facts."""
    expected = _expected(context, item, candidate, visible_ids)
    binding = item.get('binding')
    require(isinstance(binding, dict) and set(binding) == set(expected),
            'native modality execution binding has unknown or missing fields')
    require(binding == expected,
            f'native {candidate["modality"]} binding differs from executable facts')
