"""Admit a bounded GSAP scaffold and immutable root media to section dependency analysis.

Existing public Long source, full-program audio and prebuild validators remain
mandatory. This reader proves only confinement and exact runtime/source bytes;
it grants neither source authority nor renderer/playback qualification.
"""
from __future__ import annotations

import copy
from fractions import Fraction
from pathlib import Path

from graphics.graphics_render import GSAP_CORE
from studio.long_sources_html import inspect_html, local_asset
from studio.native_region_motion import admit_motion
from studio.native_runtime import digest
from studio.native_segments.dom import Node, elements, parse
from studio.native_stage_evidence import require

GSAP_ASSET = 'assets/vendor/gsap.min.js'
STATIC_ATTRIBUTES = frozenset({'id', 'class', 'style', 'lang', 'title', 'data-composition-id',
    'data-composition-src', 'data-width', 'data-height', 'data-start', 'data-duration', 'data-track-index',
    'data-motion-id'})
MEDIA_ATTRIBUTES = STATIC_ATTRIBUTES | {'src', 'muted', 'playsinline', 'preload', 'data-media-start', 'data-volume'}


def runtime_pins(project: Path) -> dict[str, str]:
    """Require the existing locally vendored GSAP, sanitized exactly like Studio staging."""
    source, staged = Path(GSAP_CORE).resolve(strict=True), project / GSAP_ASSET
    require(staged.is_file() and staged.resolve(strict=True) == staged, 'section motion needs canonical staged GSAP')
    require(staged.read_text() == source.read_text().replace('</script', '<\\/script'),
            'section GSAP differs from the existing vendored runtime')
    return {str(source): digest(source), str(staged): digest(staged)}


def implementation_pins(project: Path) -> dict[str, str]:
    """Expose exact compiler and library inputs required in the public runtime partition."""
    if not (project / GSAP_ASSET).exists():
        return {}
    pins = runtime_pins(project)
    pins.pop(str(project / GSAP_ASSET))
    files = [Path(__file__), Path(__file__).with_name('native_region_motion.py'),
             Path(__file__).with_name('native_region_contract.py')]
    return {**pins, **{str(file): digest(file) for file in files}}


def attributes_problem(document: Node) -> None:
    """Unknown DOM attributes cannot change browser behavior outside the admitted subset."""
    for node in elements(document):
        attrs = dict(node.attrs)
        require(len(attrs) == len(node.attrs), 'duplicate section DOM attribute')
        if node.tag == 'script':
            continue
        allowed = MEDIA_ATTRIBUTES if node.tag in {'video', 'audio'} else STATIC_ATTRIBUTES
        if node.tag == 'meta':
            require(attrs == {'charset': 'UTF-8'}, 'only literal UTF-8 metadata is supported')
            continue
        require(set(attrs) <= allowed, 'unsupported section DOM attribute')


def root_media(document: Node, project: Path) -> list[Node]:
    """Admit only canonical literal source elements on the unchanged full program clock."""
    found = [node for node in elements(document) if node.tag in {'video', 'audio'}]
    if not found:
        return []
    _root, rows = inspect_html((project / 'index.html').read_text())
    require(len(rows) == len(found), 'ambiguous root media inventory')
    for row in rows:
        source = project / local_asset(row.attributes['src'])
        require(source.is_file() and source.resolve(strict=True) == source, 'root media source is missing or linked')
    return found


def external_scripts(document: Node, project: Path, root: bool) -> list[Node]:
    """Only the unchanged canonical root GSAP loader may run outside compiled inline motion."""
    scripts = [node for node in elements(document) if node.tag == 'script' and node.attr('src') is not None]
    if not scripts:
        return []
    require(root and len(scripts) == 1 and dict(scripts[0].attrs) == {'src': GSAP_ASSET}
            and not scripts[0].children, 'only the exact root GSAP loader is supported')
    runtime_pins(project)
    return scripts


def admitted_document(document: Node, project: Path, context: dict) -> Node:
    """Replace only proved runtime/media nodes before ordinary static confinement checks."""
    result = copy.deepcopy(document)
    attributes_problem(result)
    root = context['root']
    clock = {'frameRate': context['canvas']['frameRate'], 'totalFrames': context['canvas']['totalFrames']}
    if not root:
        length = Fraction(context['host'].attr('data-duration')) * Fraction(clock['frameRate'])
        require(length.denominator == 1, 'motion host must have an exact frame duration')
        clock['totalFrames'] = int(length)
    scripts = external_scripts(result, project, root)
    compiled = admit_motion(result, clock, root)
    if compiled:
        runtime_pins(project)
        require(any(node.attr('src') == GSAP_ASSET for node in elements(parse((project / 'index.html').read_text()))),
            'compiled section motion requires the exact shared GSAP loader')
    media = root_media(result, project) if root else []
    for node in scripts + compiled + media:
        node.tag, node.attrs, node.children = 'span', (), []
    return result
