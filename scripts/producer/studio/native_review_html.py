"""Exact HTML review transforms on native canvases, independent of names and fps."""
from __future__ import annotations

from fractions import Fraction
import hashlib
from html.parser import HTMLParser
import json
import re

from studio.native_media_visibility import NativeElements, MARKER, additions, decimal_text, seconds, wrapper_for
from studio.native_short_delivery import clock
from studio.native_stage_evidence import require

AUDIO_ID = 'studio-dialogue-master'


class AudioSpans(HTMLParser):
    """Locate audio nodes without serializing unrelated authored HTML."""

    def __init__(self, source: str) -> None:
        """Record source offsets without normalizing unrelated composition bytes."""
        super().__init__(convert_charrefs=False)
        self.source, self.spans, self.pending, self.offsets = source, [], None, [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.feed(source)
        require(self.pending is None, 'unclosed review audio node')

    def source_offset(self) -> int:
        """Translate the parser cursor to the original source string."""
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Retain unambiguous original node identities and attributes."""
        if tag == 'audio':
            require(self.pending is None and len(dict(attrs)) == len(attrs), 'nested or duplicate audio attributes')
            self.pending = (self.source_offset(), dict(attrs))

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """HTML audio is never a self-closing void element."""
        require(tag != 'audio', 'self-closing review audio is unsupported')

    def handle_endtag(self, tag: str) -> None:
        """Finish the exact original span."""
        if tag == 'audio':
            require(self.pending is not None, 'unmatched review audio close')
            self.spans.append((*self.pending, self.source.index('>', self.source_offset()) + 1))
            self.pending = None


def without_audio(source: str) -> str:
    """Retain every non-audio character for exact equality checks."""
    for start, _attrs, end in reversed(AudioSpans(source).spans):
        source = source[:start] + source[end:]
    return source


def canvas_clock(canvas: dict) -> tuple:
    """Use the shared rational frame/sample clock without a Short duration cap."""
    timeline = clock(canvas)
    total = canvas['totalFrames']
    require(type(total) is int and total > 0 and 1 <= timeline.fps.fraction <= 60, 'invalid review frame clock')
    duration = Fraction(total, 1) / timeline.fps.fraction
    require(duration <= 86400, 'review canvas exceeds one day')
    previous = 0
    for row in canvas['segments']:
        require(type(row['startFrame']) is int and type(row['endFrameExclusive']) is int
                and row['startFrame'] == previous < row['endFrameExclusive'] <= total, 'noncontiguous review dialogue')
        previous = row['endFrameExclusive']
    require(previous == total, 'review dialogue does not cover the canvas')
    return timeline, duration


def validate_canvas(source: str, canvas: dict) -> tuple:
    """Require one named native root matching the admitted rational canvas."""
    elements = NativeElements(source)
    roots = [node for node in elements.elements if 'data-composition-id' in node.attrs]
    require(len(roots) == 1, 'review requires one standalone native composition')
    root = roots[0]; attrs = root.attrs
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', attrs['data-composition-id']) is not None,
            'invalid native composition identity')
    timeline, duration = canvas_clock(canvas)
    require(abs(Fraction(attrs['data-duration']) - duration) <= Fraction(1, 10**9)
            and abs(Fraction(attrs['data-fps']) - timeline.fps.fraction) <= Fraction(1, 10**9), 'HTML canvas clock differs')
    require(all(str(attrs.get(key, '')).isdigit() and 0 < int(attrs[key]) <= 16384
                for key in ('data-width', 'data-height')), 'invalid native review dimensions')
    return elements, root, timeline, duration


def adapt_visibility(source: str, canvas: dict) -> tuple[str, dict]:
    """Reuse proven pure-wrapper gating with the actual composition registry name."""
    elements, root, _clock, duration = validate_canvas(source, canvas)
    require(MARKER not in source, 'preserve existing review visibility adaptation')
    windows = []
    for video in [node for node in elements.elements if node.tag == 'video']:
        wrapper = wrapper_for(video, elements)
        start, length = seconds(video.attrs.get('data-start')), seconds(video.attrs.get('data-duration'))
        require(length > 0 and start + length <= duration + Fraction(1, 10**9), 'video window exceeds canvas')
        windows.append({'wrapperId': wrapper.attrs['id'], 'videoId': video.attrs['id'],
                        'startSeconds': decimal_text(start), 'endSecondsExclusive': decimal_text(start + length)})
    require(len({row['wrapperId'] for row in windows}) == len(windows), 'duplicate review wrapper')
    if not windows:
        return source, {'windows': [], 'unrelatedBytesIdentical': True}
    begin = 'const tl=gsap.timeline({paused:true});'
    end = f'window.__timelines[{json.dumps(root.attrs["data-composition-id"])}]=tl;'
    require(all(source.count(mark) == 1 for mark in (begin, end, '</head>')), 'unsupported native timeline registration')
    require(not re.search(r'\b(?:visibility|autoAlpha|display)\s*:', source.split(begin)[1].split(end)[0]),
            'review timeline already controls visibility')
    style, commands = additions(windows)
    inserts = [{'atCharacter': source.index('</head>'), 'text': style}, {'atCharacter': source.index(end), 'text': commands}]
    result = source
    for row in sorted(inserts, key=lambda row: row['atCharacter'], reverse=True):
        result = result[:row['atCharacter']] + row['text'] + result[row['atCharacter']:]
    require(result.replace(style, '', 1).replace(commands, '', 1) == source, 'unrelated review HTML changed')
    return result, {'windows': windows, 'insertions': inserts, 'unrelatedBytesIdentical': True}


def adapt_html(source: str, canvas: dict, native_long: bool = False) -> tuple[str, dict]:
    """Replace checked dialogue with one continuous final AAC while retaining pictures."""
    _elements, _root, timeline, duration = validate_canvas(source, canvas)
    spans = AudioSpans(source).spans
    require(len(spans) == len(canvas['segments']) and AUDIO_ID not in source, 'unexpected or previously adapted dialogue')
    ids = [attrs.get('id') for _, attrs, _ in spans]
    require(all(ids) and len(set(ids)) == len(ids), 'duplicate review audio identity')
    for (_start, attrs, _end), segment in zip(spans, canvas['segments'], strict=True):
        expected = {'data-start': Fraction(segment['startFrame'], 1) / timeline.fps.fraction,
                    'data-duration': Fraction(segment['endFrameExclusive'] - segment['startFrame'], 1) / timeline.fps.fraction}
        require((native_long or 'clip' in attrs.get('class', '').split()) and bool(attrs.get('src')), 'invalid native dialogue node')
        require(all(abs(Fraction(attrs.get(key, '-1')) - value) <= Fraction(1, 10**9) for key, value in expected.items()),
                'HTML dialogue differs from the admitted canvas')
    node = (f'<audio id="{AUDIO_ID}" class="clip" src="assets/studio-dialogue.m4a" data-start="0" '
            f'data-duration="{decimal_text(duration)}" data-media-start="0" data-track-index="10" data-volume="1"></audio>')
    result = source
    for index in reversed(range(len(spans))):
        start, _attrs, end = spans[index]
        result = result[:start] + (node if index == 0 else '') + result[end:]
    rest = without_audio(source)
    require(rest == without_audio(result), 'audio adaptation changed non-audio bytes')
    visibility = {'mode': 'preserved-native-long-visuals', 'unrelatedBytesIdentical': True}
    if not native_long:
        result, visibility = adapt_visibility(result, canvas)
    return result, {'audio': {'removedIds': ids, 'newId': AUDIO_ID, 'nonAudioBytesIdentical': True,
                    'nonAudioSha256': hashlib.sha256(rest.encode()).hexdigest()}, 'visibility': visibility}


def frame_points(plan: dict) -> list[dict]:
    """Select exact opening, closing, scene, cut and caption checkpoints."""
    canvas = plan['canvas']; timeline, _duration = canvas_clock(canvas)
    total = canvas['totalFrames']; values = {0, total - 1}
    if canvas.get('titleCard'):
        end = canvas['titleCard']['endFrame']; values.update((end - 1, end))
    for row in plan.get('scenes', plan.get('strategy', {}).get('scenes', [])):
        start, end = row['startFrame'], row['endFrame']; values.update((start, (start + end - 1) // 2, end - 1))
    for row in canvas['segments']:
        values.update((max(0, row['startFrame'] - 1), row['startFrame']))
    for view in canvas.get('captionViews', []):
        words = [row for row in canvas.get('occurrences', []) if view['startFrame'] <= row[3] < view['endFrame']]
        values.update(row[3] + min(2, row[4] - row[3] - 1) for row in words[:2])
    return [{'frame': frame, 'seconds': decimal_text(Fraction(frame, 1) / timeline.fps.fraction)}
            for frame in sorted(values) if 0 <= frame < total]
