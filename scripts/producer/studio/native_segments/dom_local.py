"""Whether a changed timed element of index.html can only change frames inside its own interval.

The same rules the composition isolation proof applies to a mounted composition
(``src/lib/server/native-composition-isolation.ts``): the HyperFrames runtime hides an inactive
absolutely positioned clip only with an inline ``visibility: hidden``, which a descendant's
``visibility`` (or ``content-visibility``, ``all``, counters, ``!important``) can override, and an
element in normal flow can move its siblings. A changed timed subtree is therefore local only when
its root is absolutely positioned (inline, or by a single-class rule of the document's own styles),
no element in it declares a controlling property inline or matches a document rule that does, it
holds no forbidden element (media, frames, scripts, styles, templates, links) and no descendant
carries timing or mount attributes. Anything else widens. Code finds WHERE; it judges no meaning.
"""
from __future__ import annotations

from dataclasses import dataclass

FORBIDDEN = frozenset({'iframe', 'object', 'embed', 'video', 'audio', 'source', 'track', 'template', 'meta',
                       'base', 'link', 'script', 'style', 'noscript', 'canvas', 'slot', 'frame', 'frameset',
                       'portal', 'animate', 'set', 'animatetransform', 'animatemotion', 'animatecolor',
                       'foreignobject'})
CONTROLLING = frozenset({'visibility', 'content-visibility', 'all', 'counter-reset', 'counter-increment',
                         'counter-set'})
TIMING = frozenset({'data-start', 'data-end', 'data-duration', 'data-hidden', 'data-media-start',
                    'data-track-index', 'data-track-kind', 'data-composition-src', 'data-variable-values'})
POSITIONED = frozenset({'absolute', 'fixed'})


@dataclass(frozen=True)
class DocumentStyle:
    """What the document's own style rules say: positioned single classes and controlling selectors."""

    positioned: frozenset[str]
    controlling: frozenset[str]   # '.class' / '#id' tokens named by a rule with a controlling declaration
    unscoped: bool                # a controlling rule also matches by tag, attribute or '*'


def declarations(body: str) -> list[tuple[str, str]]:
    """``(property, value)`` pairs of one declaration block, lower-cased property without a vendor prefix."""
    pairs = []
    for part in body.split(';'):
        name, colon, value = part.partition(':')
        if not colon:
            continue
        name = name.strip().lower()
        if name.startswith('-') and name.count('-') >= 2:
            name = name[name.index('-', 1) + 1:]
        pairs.append((name, value.strip().lower()))
    return pairs


def controls(body: str) -> bool:
    """A declaration block that can un-hide an inactive clip or reach outside it."""
    return any(name in CONTROLLING or '!important' in value for name, value in declarations(body))


def rules(css: str) -> list[tuple[str, str]]:
    """``(selector, body)`` of every innermost rule (nested at-rule blocks included)."""
    found, stack, start = [], [], 0
    for index, char in enumerate(css):
        if char == '{':
            stack.append((css[start:index].strip(), index + 1))
            start = index + 1
        elif char == '}' and stack:
            selector, begin = stack.pop()
            body = css[begin:index]
            found.extend([(selector, body)] if '{' not in body and not selector.startswith('@') else [])
            start = index + 1
    return found


def compounds(selector: str) -> list[str]:
    """The compound selectors of a selector list, pseudo-classes stripped."""
    parts = []
    for single in selector.split(','):
        for token in single.replace('>', ' ').replace('+', ' ').replace('~', ' ').split():
            parts.append(token.split(':', 1)[0])
    return parts


def tokens(compound: str) -> list[str]:
    """'.class' and '#id' tokens of one compound selector."""
    found, current = [], ''
    for char in compound:
        if char not in '.#':
            current += char if current else ''
            continue
        if current:
            found.append(current)
        current = char
    return found + ([current] if current else [])


def single_classes(selector: str) -> list[str]:
    """Class names of the selector-list members that are exactly one class (``.text`` in ``.shape,.text``)."""
    members = [member.strip() for member in selector.split(',')]
    return [member[1:] for member in members if member.startswith('.') and tokens(member) == [member]
            and not any(char in member for char in ' >+~:[*')]


def document_style(css: str) -> DocumentStyle:
    """Read positioned classes and controlling selectors from the document's style text."""
    positioned, controlling, unscoped = set(), set(), False
    for selector, body in rules(css):
        if any(name == 'position' and value in POSITIONED for name, value in declarations(body)):
            positioned.update(single_classes(selector))
        if not controls(body):
            continue
        parts = compounds(selector)
        unscoped |= any(not part or part[0] not in '.#' for part in parts)
        controlling.update(token for part in parts for token in tokens(part))
    return DocumentStyle(frozenset(positioned), frozenset(controlling), unscoped)


def positioned(node: object, style: DocumentStyle) -> bool:
    """Inline or single-class absolute/fixed positioning of a timed root."""
    inline = any(name == 'position' and value in POSITIONED for name, value in declarations(node.attr('style') or ''))
    return inline or bool(set((node.attr('class') or '').split()) & style.positioned)


def element_problem(node: object, style: DocumentStyle, root: bool) -> str | None:
    """Why one element of a changed timed subtree is not provably local, or None."""
    if node.tag in FORBIDDEN:
        return f'<{node.tag}>'
    if controls(node.attr('style') or ''):
        return 'an inline visibility, content-visibility, all, counter or !important declaration'
    names = {f'.{name}' for name in (node.attr('class') or '').split()}
    names |= {f'#{node.attr("id")}'} if node.attr('id') else set()
    if names & style.controlling:
        return 'a class or id a document rule gives a controlling declaration'
    if not root and any(key in TIMING for key, _value in node.attrs):
        return 'a nested timing or mount attribute'
    return None


def style_text(document: object) -> str:
    """The text of every ``<style>`` element of a parsed document (the untimed skeleton holds them)."""
    parts, stack = [], [document]
    while stack:
        node = stack.pop()
        if node.tag == 'style':
            parts.extend(child[1] for child in node.children if not hasattr(child, 'tag'))
        stack.extend(child for child in node.children if hasattr(child, 'tag'))
    return '\n'.join(parts)


def subtree_problem(root: object, style: DocumentStyle) -> str | None:
    """Why a changed timed subtree could change frames outside its interval, or None."""
    if style.unscoped:
        return 'a document rule with a controlling declaration matches by tag, attribute or *'
    if root.tag in FORBIDDEN:
        return f'<{root.tag}>'
    if not positioned(root, style):
        return 'its timed root is not absolutely positioned'
    stack, first = [root], True
    while stack:
        node = stack.pop()
        problem = element_problem(node, style, first)
        if problem:
            return problem
        first = False
        stack.extend(child for child in node.children if hasattr(child, 'tag'))
    return None
