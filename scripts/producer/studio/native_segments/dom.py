"""Structural diff of two rendered HTML documents down to the timed elements that changed.

HyperFrames shows an element carrying ``data-start`` and ``data-duration`` only inside that
interval. This module finds WHERE two documents differ: it parses both into element trees,
replaces every outermost timed subtree with a placeholder, and requires the remaining
untimed skeleton (head, styles, scripts, the canvas root and every untimed wrapper) to be
identical. Each differing timed subtree then contributes its old and new intervals. Any
skeleton difference widens to the whole program with a stated reason, and so does a changed
timed subtree that fails the composition-style locality checks of ``dom_local`` (absolutely
positioned root, no descendant that can override the runtime's inline visibility, no media,
frame, script, style or link, no nested timing). It judges no meaning; the revision's
dependency probes check the claim against real captured frames before reuse.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from html.parser import HTMLParser

from studio.native_segments.dom_local import document_style, style_text, subtree_problem

VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param',
                  'source', 'track', 'wbr'})
MAX_NODES = 200_000


@dataclass
class Node:
    """One element (or the document root) with its ordered attributes and children."""

    tag: str
    attrs: tuple[tuple[str, str | None], ...] = ()
    children: list = field(default_factory=list)

    def attr(self, name: str) -> str | None:
        """The first value of an attribute, or None."""
        return next((value for key, value in self.attrs if key == name), None)


class _TreeBuilder(HTMLParser):
    """Strict-enough tree builder: mismatched end tags are a parse error, not a guess."""

    def __init__(self) -> None:
        """Start with an empty document root."""
        super().__init__(convert_charrefs=False)
        self.stack, self.count, self.errors = [Node('#document')], 0, []

    def _add(self, value: object) -> None:
        """Append one node or text token to the open element, within the node bound."""
        self.count += 1
        if self.count > MAX_NODES:
            raise ValueError('rendered document exceeds its node bound')
        self.stack[-1].children.append(value)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Open an element (void elements close immediately)."""
        node = Node(tag, tuple(attrs))
        self._add(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """A self-closed element."""
        self._add(Node(tag, tuple(attrs)))

    def handle_endtag(self, tag: str) -> None:
        """Close the innermost open element; any other end tag is a structural error."""
        if tag in VOID:
            return
        if len(self.stack) < 2 or self.stack[-1].tag != tag:
            self.errors.append(f'unexpected </{tag}>')
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        """Text, kept byte for byte (whitespace changes count as changes)."""
        self._add(('#text', data))

    def handle_entityref(self, name: str) -> None:
        """Entity references stay unexpanded so the comparison is exact."""
        self._add(('#entity', name))

    def handle_charref(self, name: str) -> None:
        """Character references stay unexpanded."""
        self._add(('#charref', name))

    def handle_comment(self, data: str) -> None:
        """Comments are part of the untimed skeleton when outside timed elements."""
        self._add(('#comment', data))

    def handle_decl(self, decl: str) -> None:
        """The doctype."""
        self._add(('#decl', decl))


def parse(text: str) -> Node:
    """Parse one rendered document; unbalanced markup raises instead of being repaired."""
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    if builder.errors or len(builder.stack) != 1:
        raise ValueError(f'rendered document is not balanced: {builder.errors[:3] or "unclosed elements"}')
    return builder.stack[0]


def interval(node: Node) -> tuple[Fraction, Fraction] | None:
    """The [start, end) seconds of a timed element, or None when it is not timed."""
    start, duration = node.attr('data-start'), node.attr('data-duration')
    if start is None or duration is None:
        return None
    try:
        begin, length = Fraction(start), Fraction(duration)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'timed element has a non-numeric interval: {start!r}/{duration!r}') from error
    if begin < 0 or length <= 0:
        raise ValueError(f'timed element has an invalid interval: {start!r}/{duration!r}')
    return begin, begin + length


def skeleton(node: object, timed: list) -> tuple:
    """Hashable untimed structure; outermost timed subtrees become ordered placeholders."""
    if not isinstance(node, Node):
        return node
    if node.tag != '#document' and interval(node) is not None:
        timed.append(node)
        return ('#timed', len(timed) - 1)
    return (node.tag, node.attrs, tuple(skeleton(child, timed) for child in node.children))


def elements(node: Node) -> list[Node]:
    """Every element below a node (depth-first, the node itself excluded)."""
    found, stack = [], [child for child in node.children if isinstance(child, Node)]
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(child for child in current.children if isinstance(child, Node))
    return found


def frame_range(seconds: tuple[Fraction, Fraction], rate: Fraction) -> list[int]:
    """Frames whose presentation time can fall in the interval (conservative floor/ceil)."""
    return [math.floor(seconds[0] * rate), math.ceil(seconds[1] * rate)]


def timed_changes(before: str, after: str, rate: Fraction) -> dict:
    """Changed frame ranges of the timed elements that differ, or a stated whole-program widening."""
    old_timed, new_timed, document = [], [], parse(after)
    old_shape, new_shape = skeleton(parse(before), old_timed), skeleton(document, new_timed)
    if old_shape != new_shape:
        return {'global': True, 'reason': 'untimed document structure changed (head, styles, scripts, canvas '
                'root, wrappers or the number/order of timed elements)', 'ranges': []}
    changed = [node for old, new in zip(old_timed, new_timed) if not _same(old, new) for node in (old, new)]
    style = document_style(style_text(document))
    unbounded = next(((node, problem) for node in changed if (problem := subtree_problem(node, style))), None)
    if unbounded:
        return {'global': True, 'reason': f'changed timed element #{unbounded[0].attr("id")} is not provably local: '
                f'{unbounded[1]}', 'ranges': []}
    ranges = [frame_range(seconds, rate) for node in changed for seconds in timed_intervals(node)]
    return {'global': False, 'reason': 'changed timed elements only', 'ranges': sorted(ranges)}


def timed_intervals(node: Node) -> list[tuple[Fraction, Fraction]]:
    """The element's own interval and every nested timed interval (a nested clip is never assumed hidden)."""
    return [seconds for current in (node, *elements(node)) if (seconds := interval(current)) is not None]


def _same(old: Node, new: Node) -> bool:
    """Exact recursive equality including nested timed elements."""
    if old.tag != new.tag or old.attrs != new.attrs or len(old.children) != len(new.children):
        return False
    for left, right in zip(old.children, new.children):
        if isinstance(left, Node) != isinstance(right, Node):
            return False
        if isinstance(left, Node) and not _same(left, right):
            return False
        if not isinstance(left, Node) and left != right:
            return False
    return True


def composition_mounts(text: str, file: str, rate: Fraction) -> list[list[int]]:
    """Frame ranges of every timed element that mounts one composition file."""
    mounts = [node for node in elements(parse(text)) if node.attr('data-composition-src') == file]
    if any(interval(node) is None for node in mounts):
        raise ValueError(f'composition {file} is mounted by an untimed element')
    return sorted(frame_range(interval(node), rate) for node in mounts)
