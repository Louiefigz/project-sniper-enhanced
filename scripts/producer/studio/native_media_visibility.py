"""Add exact media-only wrapper windows to an editable native Studio fork.

The original HTML is preserved byte-for-byte around two recorded insertions.
Clip visibility, media timing, crops, text, audio and production files are untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
from html.parser import HTMLParser
import json
import re

VERSION = 'native-media-wrapper-display-v1'
MARKER = 'sniper-studio-media-visibility'
TIMELINE_START = 'const tl=gsap.timeline({paused:true});'
TIMELINE_END = 'window.__timelines=window.__timelines||{};window.__timelines["native-canvas"]=tl;'
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
SAFE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]*\Z')
DECIMAL = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,20})?\Z')


@dataclass
class Element:
    """Retain just enough DOM structure to prove a wrapper owns one video only."""
    tag: str
    attrs: dict[str, str | None]
    parent: Element | None
    children: list[Element] = field(default_factory=list)
    has_text: bool = False


class NativeElements(HTMLParser):
    """Parse native HTML without serializing or normalizing any source bytes."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[Element] = []
        self.elements: list[Element] = []
        self.ids: dict[str, Element] = {}
        self.feed(source)
        self.close()
        if self.stack:
            raise ValueError('Unclosed native HTML element')

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        """Require unambiguous attribute and global element identities."""
        values = dict(attrs)
        if len(values) != len(attrs):
            raise ValueError('Duplicate native HTML attribute')
        node = Element(tag, values, self.stack[-1] if self.stack else None)
        identity = values.get('id')
        if identity and identity in self.ids:
            raise ValueError(f'Duplicate native HTML id: {identity}')
        if identity:
            self.ids[identity] = node
        if node.parent:
            node.parent.children.append(node)
        self.elements.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple]) -> None:
        """Honor explicit self-closing syntax without changing the source."""
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """Reject malformed nesting instead of guessing a wrapper boundary."""
        if not self.stack or self.stack[-1].tag != tag:
            raise ValueError(f'Malformed native HTML closing tag: {tag}')
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        """Mark meaningful text that must never disappear with a media wrapper."""
        if self.stack and data.strip():
            self.stack[-1].has_text = True


def seconds(value: str | None) -> Fraction:
    """Admit finite nonnegative native decimal seconds without float rounding."""
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise ValueError(f'Invalid native media clock: {value}')
    result = Fraction(value)
    if result > 86400:
        raise ValueError('Native media window exceeds one day')
    return result


def decimal_text(value: Fraction) -> str:
    """Serialize a finite decimal clock inherited from HTML attributes exactly."""
    with localcontext() as context:
        context.prec = 60
        text = format(Decimal(value.numerator) / Decimal(value.denominator), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def wrapper_for(video: Element, elements: NativeElements) -> Element:
    """Require the generated crop and any pose ancestors to contain only this video."""
    identity = video.attrs.get('id', '')
    if not SAFE_ID.fullmatch(identity) or 'clip' not in (video.attrs.get('class') or '').split():
        raise ValueError('Expected an identified native video clip')
    source = re.fullmatch(r'source-([0-9]+)-([0-9]+)', identity)
    target = f'source-crop-{source[1]}-{source[2]}' if source else f'{identity}-crop'
    wrapper = elements.ids.get(target)
    current = video.parent
    while current:
        validate_wrapper(current)
        if current is wrapper:
            return wrapper
        current = current.parent
    raise ValueError(f'Missing media-only native crop wrapper: {target}')


def validate_wrapper(node: Element) -> None:
    """Reject shared, timed, textual or visibility-authored ancestor containers."""
    attrs = node.attrs
    if node.tag != 'div' or node.has_text or len(node.children) != 1:
        raise ValueError('Native media wrapper contains unrelated content')
    if any(key in attrs for key in ('data-start', 'data-duration', 'data-composition-id')) \
            or 'clip' in (attrs.get('class') or '').split():
        raise ValueError('Refusing to control an already timed wrapper')
    if re.search(r'(?:visibility|display)\s*:', attrs.get('style') or '', re.I):
        raise ValueError('Native wrapper already authors visibility/display')


def media_windows(source: str) -> list[dict[str, str]]:
    """Read every native video window and validate its exact exclusive end."""
    elements = NativeElements(source)
    canvas = elements.ids.get('native-canvas')
    if not canvas or canvas.attrs.get('data-composition-id') != 'native-canvas':
        raise ValueError('Expected the native canvas composition')
    total = seconds(canvas.attrs.get('data-duration'))
    result = []
    for video in [node for node in elements.elements if node.tag == 'video']:
        wrapper = wrapper_for(video, elements)
        start = seconds(video.attrs.get('data-start'))
        duration = seconds(video.attrs.get('data-duration'))
        if not video.attrs.get('src') or duration <= 0 or start + duration > total + Fraction(1, 10**12):
            raise ValueError('Native video has missing source or out-of-bounds window')
        result.append({'wrapperId': wrapper.attrs['id'], 'videoId': video.attrs['id'],
                       'startSeconds': decimal_text(start), 'endSecondsExclusive': decimal_text(start + duration)})
    if not result or len({row['wrapperId'] for row in result}) != len(result):
        raise ValueError('Expected unique media-only wrapper windows')
    return result


def additions(windows: list[dict[str, str]]) -> tuple[str, str]:
    """Gate descendants through display, including CSS state before the first seek."""
    initial = ''.join(f"#{row['wrapperId']}{{display:{'block' if row['startSeconds'] == '0' else 'none'}}}"
                      for row in windows)
    style = f'<style id="{MARKER}">{initial}</style>'
    commands = [f'/* {MARKER}:begin */']
    for row in windows:
        target = json.dumps('#' + row['wrapperId'])
        state = 'block' if row['startSeconds'] == '0' else 'none'
        commands.extend([f'tl.set({target},{{display:"{state}"}},0);',
                         f'tl.set({target},{{display:"block"}},{row["startSeconds"]});',
                         f'tl.set({target},{{display:"none"}},{row["endSecondsExclusive"]});'])
    commands.append(f'/* {MARKER}:end */')
    return style, '\n'.join(commands) + '\n'


def adapt_media_visibility(source: str) -> tuple[str, dict]:
    """Return a deterministic Studio-only transform and exact auditable insertions."""
    if MARKER in source:
        raise ValueError('Preserve existing native media visibility adaptation')
    if any(source.count(marker) != 1 for marker in (TIMELINE_START, TIMELINE_END, '</head>')):
        raise ValueError('Expected one native paused timeline and HTML head')
    timeline = source.split(TIMELINE_START, 1)[1].split(TIMELINE_END, 1)[0]
    if re.search(r'\b(?:visibility|autoAlpha|display)\s*:', timeline):
        raise ValueError('Native timeline already authors visibility; review conflicts first')
    windows = media_windows(source)
    style, commands = additions(windows)
    insertions = [{'atCharacter': source.index('</head>'), 'text': style},
                  {'atCharacter': source.index(TIMELINE_END), 'text': commands}]
    adapted = source
    for insertion in sorted(insertions, key=lambda row: row['atCharacter'], reverse=True):
        at = insertion['atCharacter']
        adapted = adapted[:at] + insertion['text'] + adapted[at:]
    restored = adapted.replace(style, '', 1).replace(commands, '', 1)
    if restored != source:
        raise ValueError('Visibility adaptation changed unrelated HTML bytes')
    digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
    return adapted, {'version': VERSION, 'scope': 'editable-Studio-only', 'windows': windows,
                     'insertions': insertions, 'sourceSha256': digest(source), 'adaptedSha256': digest(adapted),
                     'unrelatedBytesIdentical': True, 'mediaTimingUnchanged': True,
                     'browserPlaybackVerified': False}
