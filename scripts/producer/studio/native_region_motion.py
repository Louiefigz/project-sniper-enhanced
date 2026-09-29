"""Compile a closed host-local motion declaration to the existing paused GSAP runtime.

This is dependency admission, not a new renderer or a motion-quality approval.
No callbacks, arbitrary expressions, global target strings or sibling reads are
accepted. Real native/encoded probes remain necessary for runtime qualification.
"""
from __future__ import annotations

import json
import math
import re
from fractions import Fraction

from studio.native_segments.dom import Node, elements
from studio.native_stage_evidence import require

VERSION = 'native-section-gsap-v1'
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}')
PROPERTIES = frozenset({'opacity', 'x', 'y', 'scale', 'scaleX', 'scaleY', 'rotation'})
EASES = frozenset({'none', 'power1.in', 'power1.out', 'power1.inOut',
                  'power2.in', 'power2.out', 'power2.inOut'})


def encoded(value: object) -> str:
    """Emit deterministic JavaScript JSON without HTML-end-tag interpolation."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')


def properties(value: object) -> dict:
    """Allow bounded numerical GSAP transform/opacity values only."""
    require(type(value) is dict and value and set(value) <= PROPERTIES, 'unsupported section motion properties')
    require(all(type(number) in (int, float) and math.isfinite(number) and abs(number) <= 10000
                for number in value.values()), 'motion values must be finite bounded numbers')
    require('opacity' not in value or 0 <= value['opacity'] <= 1, 'motion opacity must be zero through one')
    return value


def validate_motion(value: object) -> dict:
    """Require one closed timeline and literal host-local, frame-bound tween inventory."""
    require(type(value) is dict and set(value) == {'schemaVersion', 'rule', 'compositionId',
            'frameRate', 'totalFrames', 'tweens'} and type(value['schemaVersion']) is int
            and value['schemaVersion'] == 1 and value['rule'] == VERSION, 'invalid section motion declaration')
    require(type(value['compositionId']) is str and IDENTIFIER.fullmatch(value['compositionId']),
            'invalid motion composition identity')
    require(type(value['frameRate']) is str and re.fullmatch(r'[1-9][0-9]*/[1-9][0-9]*', value['frameRate'])
            and Fraction(value['frameRate']) <= 120 and type(value['totalFrames']) is int
            and 0 < value['totalFrames'] <= 432000, 'invalid section motion clock')
    require(type(value['tweens']) is list and len(value['tweens']) <= 256, 'invalid bounded motion tween inventory')
    for tween in value['tweens']:
        validate_tween(tween, value['totalFrames'])
    return value


def validate_tween(row: object, total: int) -> None:
    """Reject callbacks, relative values, dynamic selectors and out-of-range motion."""
    require(type(row) is dict and set(row) == {'target', 'startFrame', 'endFrame', 'from', 'to', 'ease'},
            'invalid section motion tween')
    require(type(row['target']) is str and IDENTIFIER.fullmatch(row['target']), 'invalid host-local motion target')
    require(type(row['startFrame']) is type(row['endFrame']) is int
            and 0 <= row['startFrame'] < row['endFrame'] <= total, 'motion tween leaves its composition clock')
    require(type(row['ease']) is str and row['ease'] in EASES, 'unsupported motion ease')
    require(set(properties(row['from'])) == set(properties(row['to'])), 'motion property endpoints differ')


def compile_motion(value: dict) -> str:
    """Generate only literal GSAP operations against descendants of the one declared host."""
    value = validate_motion(value)
    key, rate = value['compositionId'], Fraction(value['frameRate'])
    selector = f'[data-composition-id="{key}"]'
    lines = ['(() => {', f'const root = document.querySelector({encoded(selector)});',
             'if (!root) throw new Error("Missing section motion host");',
             'const timeline = gsap.timeline({paused:true});',
             f'timeline.to({{}},{{duration:{float(value["totalFrames"] / rate)}}},0);']
    for row in value['tweens']:
        target = f'[data-motion-id="{row["target"]}"]'
        options = {**row['to'], 'ease': row['ease'], 'duration': float((row['endFrame'] - row['startFrame']) / rate),
                   'immediateRender': False}
        lines.append(f'timeline.fromTo(root.querySelector({encoded(target)}),'
                     f'{encoded(row["from"])},{encoded(options)},{float(row["startFrame"] / rate)});')
    lines += ['window.__timelines = window.__timelines || {};',
              f'window.__timelines[{encoded(key)}] = timeline;', '})();']
    return '\n'.join(lines)


def motion_markup(value: dict) -> str:
    """Emit the declaration and its exact compiled program for authored composition staging."""
    code = compile_motion(value)
    return (f'<script type="application/json" data-native-section-motion="{VERSION}">{encoded(value)}</script>'
            f'<script data-native-section-compiled="{VERSION}">{code}</script>')


def script_text(node: Node) -> str:
    """Only literal script text can participate in the exact compiler comparison."""
    require(all(type(child) is tuple and child[0] == '#text' for child in node.children),
            'motion script is not literal text')
    return ''.join(child[1] for child in node.children)


def admit_motion(document: Node, clock: dict, root: bool = False) -> list[Node]:
    """Check generated bytes, exact clock, unique own host and every actual target."""
    scripts = [node for node in elements(document) if node.tag == 'script' and node.attr('src') is None]
    if not scripts:
        return []
    require(len(scripts) == 2, 'section scripts require exactly one declaration and generated program')
    declaration = next((node for node in scripts if node.attr('type') == 'application/json'), None)
    require(declaration is not None and dict(declaration.attrs) ==
            {'type': 'application/json', 'data-native-section-motion': VERSION}, 'invalid section motion script attributes')
    compiled = next(node for node in scripts if node is not declaration)
    require(dict(compiled.attrs) == {'data-native-section-compiled': VERSION}, 'invalid compiled motion script attributes')
    value = validate_motion(json.loads(script_text(declaration)))
    require(script_text(declaration) == encoded(value), 'motion declaration must use exact canonical generated bytes')
    require(value['frameRate'] == clock['frameRate'] and value['totalFrames'] == clock['totalFrames'],
            'declared motion differs from exact composition clock')
    hosts = [node for node in elements(document) if node.attr('data-composition-id') == value['compositionId']]
    require(len(hosts) == 1, 'motion needs one unique declared host')
    targets = [node.attr('data-motion-id') for node in elements(hosts[0]) if node.attr('data-motion-id') is not None]
    require(len(targets) == len(set(targets)) and all(row['target'] in targets for row in value['tweens']),
            'motion targets must be actual unique descendants of their own host')
    require(not root or not value['tweens'], 'root timeline cannot animate section or media elements')
    require(script_text(compiled) == compile_motion(value), 'section compiled script differs from cold generated bytes')
    return scripts
