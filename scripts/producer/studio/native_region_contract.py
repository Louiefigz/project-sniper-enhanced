"""Cold-derived bounded static composition isolation; not Long runtime qualification.

This deliberately smaller subset reuses the section DOM parser and visibility
guards. Authored scripts, external styles, active media and dynamic CSS cannot
establish locality. Schema-1 preview maps remain schedules only; schema-2 maps
with this derivation are re-created from actual bytes before their claims count.
"""
from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_segments.dom import Node, elements, interval, parse
from studio.native_segments.dom_local import controls, declarations, document_style, positioned, rules, style_text
from studio.native_segments.long_plan import identity
from studio.native_stage_evidence import require

DERIVATION = 'native-root-clock-isolation-v2'
RULE = 'native-section-isolation-v2'
REGIONS = 'REVIEW-REGIONS.json'
FILE = re.compile(r'compositions/([a-zA-Z0-9][a-zA-Z0-9_-]{0,79})\.html')
TAGS = frozenset({'html', 'head', 'body', 'template', 'div', 'span', 'p', 'strong', 'em', 'b', 'i',
                  'u', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'small', 'style', 'meta', 'title'})
PROPERTIES = frozenset({'position', 'left', 'right', 'top', 'bottom', 'width', 'height', 'color',
    'background', 'background-color', 'opacity', 'transform', 'transform-origin', 'font', 'font-size',
    'font-family', 'font-weight', 'font-style', 'line-height', 'letter-spacing', 'text-align',
    'text-transform', 'text-decoration', 'white-space', 'padding', 'margin', 'border', 'border-radius',
    'border-color', 'border-width', 'box-sizing', 'overflow', 'display', 'z-index'})
SELECTOR = re.compile(r'(?:[.#]?[a-zA-Z_][a-zA-Z0-9_-]*)(?:\s+[.#]?[a-zA-Z_][a-zA-Z0-9_-]*)*')
NAMESPACE = re.compile(r'\[data-composition-id="([a-zA-Z0-9][a-zA-Z0-9_-]{0,79})"\](?:\s+(.*))?')


def selector_supported(selector: str) -> bool:
    """Allow simple descendants, optionally rooted at one literal composition namespace."""
    scoped = NAMESPACE.fullmatch(selector)
    return bool(SELECTOR.fullmatch(selector) or scoped and
                (scoped[2] is None or SELECTOR.fullmatch(scoped[2])))


def composition_style_problem(document: Node, composition_id: str) -> str | None:
    """Every composition stylesheet selector must remain inside its own mounted root."""
    selectors = [item.strip() for selector, _body in rules(style_text(document)) for item in selector.split(',')]
    for selector in selectors:
        scoped = NAMESPACE.fullmatch(selector)
        if scoped is None or scoped[1] != composition_id or not selector_supported(selector):
            return 'composition stylesheet selector escapes its owning namespace'
    return None


def style_problem(css: str, inline: bool = False) -> str | None:
    """Accept only ordinary static declarations/selectors; unknown CSS is not a local proof."""
    if any(token in css.lower() for token in ('@', '\\', '/*', 'url(', 'var(', 'expression(', '!')):
        return 'dynamic, escaped, external or controlling CSS'
    if controls(css):
        return 'controlling CSS declaration'
    blocks = [('inline', css)] if inline else rules(css)
    if not inline and (css.count('{') != len(blocks) or css.count('}') != len(blocks)):
        return 'nested or malformed CSS'
    for selector, body in blocks:
        if not inline and any(not selector_supported(item.strip()) for item in selector.split(',')):
            return 'unsupported relational CSS selector'
        if any(name not in PROPERTIES for name, _value in declarations(body)):
            return 'unsupported CSS property'
    return None


def static_problem(document: Node) -> str | None:
    """Reject executable/dynamic markup anywhere, including inactive or template content."""
    for node in elements(document):
        if node.tag not in TAGS:
            return f'unsupported dynamic or executable element <{node.tag}>'
        attrs = [name for name, _value in node.attrs]
        if len(attrs) != len(set(attrs)) or any(name.startswith('on') or name in
                {'visibility', 'data-variable-values', 'data-hidden', 'data-end'} for name in attrs):
            return 'duplicate, event, visibility or dynamic timing attribute'
        problem = style_problem(node.attr('style') or '', True)
        if problem:
            return problem
    return style_problem(style_text(document))


def admitted_problem(document: Node, project: Path, context: dict) -> str | None:
    """Recognize only cold-compiled motion and literal immutable root sources."""
    from studio.native_region_runtime import admitted_document
    try:
        return static_problem(admitted_document(document, project, context))
    except (ValueError, KeyError, TypeError, OSError) as error:
        return f'unsupported section runtime: {error}'


def mounts(document: Node) -> list[Node]:
    """All root-clock composition mounts; timed ancestors or nested mounts are refused."""
    found, pending = [], [(document, False)]
    while pending:
        node, ancestor_timed = pending.pop()
        if node.attr('data-composition-src') is not None:
            require(not ancestor_timed, 'region mount has a timed ancestor')
            found.append(node)
        timed = ancestor_timed or node.attr('data-start') is not None
        pending.extend((child, timed) for child in reversed(node.children) if isinstance(child, Node))
    return found


def mount_range(node: Node, canvas: dict) -> list[int]:
    """Require exact rational frame boundaries; ambiguous fractional mounts stay unsupported."""
    seconds = interval(node)
    require(seconds is not None, 'region mount needs explicit start and duration')
    bounds = [value * Fraction(canvas['frameRate']) for value in seconds]
    require(all(value.denominator == 1 for value in bounds), 'region mount is not frame-exact')
    values = list(map(int, bounds))
    require(0 <= values[0] < values[1] <= canvas['totalFrames'], 'region mount is outside the Long clock')
    return values


def composition_isolation(file: Path, host: Node, context: dict) -> dict:
    """Recompute a scoped verdict from static content and a unique absolutely positioned host."""
    document = parse(file.read_text())
    problem = context['problem'] or admitted_problem(document, file.parent.parent,
                {'root': False, 'canvas': context['canvas'], 'host': host})
    problem = problem or composition_style_problem(document, host.attr('data-composition-id'))
    roots = [node for node in elements(document) if node.attr('data-composition-id') is not None]
    if len(roots) != 1 or roots[0].attr('data-composition-id') != host.attr('data-composition-id'):
        problem = problem or 'composition needs its unique matching host root'
    if not positioned(host, document_style('')):
        problem = problem or 'composition host must be absolutely positioned inline'
    if ('display', 'contents') in declarations(host.attr('style') or ''):
        problem = problem or 'composition host cannot dissolve its absolute layout box'
    nested = [node for node in elements(document) if node.attr('data-start') is not None
              or node.attr('data-composition-src') is not None]
    if nested:
        problem = problem or 'nested timing or composition mounts are unsupported'
    if problem:
        return {'status': 'global', 'reason': problem}
    clock = {key: roots[0].attr(key) for key in ('data-composition-id', 'data-width', 'data-height', 'data-duration')}
    return {'status': 'scoped', 'rule': RULE, 'globalSha256': identity({'rule': RULE, 'root': clock})}


def derive_region_map(project: Path, canvas: dict) -> dict:
    """Derive all actual mounts and isolation claims; the returned map grants no media approval."""
    document = parse((project / 'index.html').read_text())
    hosts = mounts(document)
    require(1 <= len(hosts) <= 256, 'one to 256 actual composition mounts required')
    filenames = [host.attr('data-composition-src') for host in hosts]
    identities = [host.attr('data-composition-id') for host in hosts]
    require(len(set(filenames)) == len(hosts) and all(identities) and len(set(identities)) == len(hosts),
            'region mounts need unique files and composition identities')
    all_ids = [node.attr('data-composition-id') for node in elements(document)
               if node.attr('data-composition-id') is not None]
    require(len(all_ids) == len(set(all_ids)), 'root and mounted composition identities must not collide')
    problem = admitted_problem(document, project, {'root': True, 'canvas': canvas})
    rows = [_region(project, host, (canvas, problem)) for host in hosts]
    global_reason = next((row['isolation']['reason'] for row in rows if row['isolation']['status'] == 'global'), None)
    if global_reason:
        rows = [{**row, 'isolation': {'status': 'global', 'reason': global_reason}} for row in rows]
    return {'schemaVersion': 2, 'derivation': DERIVATION,
            'units': sorted(rows, key=lambda row: (row['startFrame'], row['id']))}


def _region(project: Path, host: Node, state: tuple[dict, str | None]) -> dict:
    """Describe one canonical mounted composition on the immutable full canvas."""
    canvas, problem = state
    name = host.attr('data-composition-src')
    match = FILE.fullmatch(name)
    require(match is not None, 'region mount requires a canonical composition HTML file')
    file = project / name
    require(file.is_file() and file.resolve(strict=True) == file, 'region composition is missing or linked')
    start, end = mount_range(host, canvas)
    return {'id': match[1], 'file': name, 'startFrame': start, 'endFrame': end,
            'isolation': composition_isolation(file, host, {'problem': problem, 'canvas': canvas})}


def read_region_map(project: Path, canvas: dict) -> list[dict]:
    """Reject stale, forged or differently-versioned region evidence by full cold derivation."""
    file = project / REGIONS
    require(file.is_file() and file.resolve(strict=True) == file, 'missing canonical derived region map')
    value = bound_json(file)
    require(identity(value) == identity(derive_region_map(project, canvas)),
            'region isolation map differs from current executable inputs')
    return value['units']
