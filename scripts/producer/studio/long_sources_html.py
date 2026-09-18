"""Map explicit native long-form media without reserializing graphics or motion."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import PurePosixPath
import re

from edit.selected_sources_media import decimal
from studio.native_stage_evidence import require


@dataclass(frozen=True)
class MediaElement:
    """One literal root-timeline media element and its exact original text range."""

    kind: str
    attributes: dict
    tag: str
    offset: int


def number(value: str) -> Fraction:
    """Admit finite nonnegative literal seconds; reject relative/dynamic clocks."""
    require(isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+)?', value) is not None,
            'long-form media needs literal nonnegative seconds')
    return Fraction(value)


class MediaParser(HTMLParser):
    """Observe elements and original offsets; leave all authored bytes intact."""

    def __init__(self, text: str) -> None:
        """Retain line offsets so replacements touch only the selected attributes."""
        super().__init__(convert_charrefs=False)
        self.lines = text.splitlines(keepends=True)
        self.media: list[MediaElement] = []
        self.root = None
        self.feed(text)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Require unambiguous static media, with explicit duration and identity."""
        attributes = dict(attrs)
        if self.root is None and 'data-composition-id' in attributes and 'data-composition-src' not in attributes:
            self.root = attributes
        if tag not in ('video', 'audio'):
            require(tag != 'source', 'long-form preparation requires media src on its video/audio element')
            return
        require(len(attributes) == len(attrs), 'long-form media has duplicate attributes')
        require('data-playback-rate' not in attributes and 'data-playback-start' not in attributes,
                'long-form preparation currently supports speed-one media only')
        require(bool(attributes.get('id')), 'long-form media requires a stable ID')
        require(tag != 'video' or 'muted' in attributes, 'long-form video must keep audio on its separate track')
        line, column = self.getpos()
        offset = sum(len(value) for value in self.lines[:line - 1]) + column
        self.media.append(MediaElement(tag, attributes, self.get_starttag_text(), offset))


def inspect_html(text: str) -> tuple[dict, list[MediaElement]]:
    """Require a landscape root and bounded explicit media on its existing clock."""
    parsed = MediaParser(text)
    root = parsed.root
    require(root is not None, 'long-form source has no native composition root')
    width, height = number(root.get('data-width', '')), number(root.get('data-height', ''))
    require(width > height > 0, 'long-form preparation requires the existing landscape canvas')
    duration = number(root.get('data-duration', ''))
    require(0 < duration <= 3600, 'long-form preparation currently supports programs up to one hour')
    require(0 < len(parsed.media) <= 256, 'long-form source has no media or exceeds its bound')
    require(len({row.attributes['id'] for row in parsed.media}) == len(parsed.media), 'duplicate long-form media IDs')
    for row in parsed.media:
        attrs = row.attributes
        start, length = number(attrs.get('data-start', '')), number(attrs.get('data-duration', ''))
        require(length > 0 and start + length <= duration + Fraction(1, 1000000), 'media leaves the original program clock')
        number(attrs.get('data-media-start', '0'))
        local_asset(attrs.get('src', ''))
    return root, parsed.media


def local_asset(value: str) -> str:
    """Require one canonical literal asset path inside the project."""
    require(isinstance(value, str) and re.fullmatch(r'assets/[A-Za-z0-9_./-]+', value) is not None
            and '..' not in PurePosixPath(value).parts and str(PurePosixPath(value)) == value,
            'long-form media requires a canonical local assets/ path')
    return value


def change_attribute(tag: str, name: str, value: str) -> str:
    """Replace one quoted attribute or insert the standard optional source offset."""
    pattern = rf'(\s{re.escape(name)}\s*=\s*)([\'\"])(.*?)\2'
    matches = list(re.finditer(pattern, tag, flags=re.IGNORECASE))
    if not matches:
        require(name == 'data-media-start' and re.search(rf'\s{re.escape(name)}\s*=', tag, re.IGNORECASE) is None,
                f'long-form media needs a quoted {name}')
        return tag[:-1] + f' data-media-start="{value}">'
    require(len(matches) == 1, 'ambiguous long-form attribute replacement')
    match = matches[0]
    return tag[:match.start(3)] + value + tag[match.end(3):]


def prepared_mapping(row: MediaElement, bindings: dict, result: dict) -> dict | None:
    """Keep the original output clock and translate only selected source offsets."""
    attrs = row.attributes
    source = bindings.get(attrs['src'])
    if source is None:
        return None
    start = number(attrs.get('data-media-start', '0'))
    end = start + number(attrs['data-duration'])
    candidates = [section[row.kind] for section in result['sections']
                  if section['sourceFile'] == source['file'] and section[row.kind] is not None]
    media = next((asset for asset in candidates if Fraction(asset['sourceStart']) <= start
                  and Fraction(asset['sourceEnd']) + Fraction(1, 10 ** 9) >= end), None)
    require(media is not None, f'prepared long-form range does not cover {attrs["id"]}')
    local = start - Fraction(media['sourceOrigin'])
    require(local >= 0, 'negative prepared long-form source offset')
    return {'id': attrs['id'], 'kind': row.kind, 'originalFile': attrs['src'],
            'originalStart': str(start), 'originalEnd': str(end),
            'sourceOrigin': media['sourceOrigin'], 'preparedFile': media['file'],
            'preparedStart': str(local), 'asset': media}


def transform(text: str, bindings: dict, result: dict) -> tuple[str, list[dict]]:
    """Preserve every other byte, including captions, timelines, masks and audio gains."""
    _root, media = inspect_html(text)
    rewritten, mappings = text, []
    for row in reversed(media):
        mapping = prepared_mapping(row, bindings, result)
        if mapping is None:
            continue
        tag = change_attribute(row.tag, 'src', mapping['preparedFile'])
        tag = change_attribute(tag, 'data-media-start', decimal(Fraction(mapping['preparedStart'])))
        rewritten = rewritten[:row.offset] + tag + rewritten[row.offset + len(row.tag):]
        mappings.append(mapping)
    return rewritten, list(reversed(mappings))
