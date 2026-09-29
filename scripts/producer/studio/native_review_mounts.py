"""Identify one native review root and the catalog composition mounts it contains.

Current native builds mount catalog titles and graphics as nested
``data-composition-src`` hosts inside the generated root composition. Review
preparation accepts exactly that shape: one top-level inline composition, and
every other composition element an empty mount host on the root clock whose
source file is admitted with the checked export and contains no media that the
review cannot replace (audio) or gate (video). Anything else is refused.
"""
from __future__ import annotations

from fractions import Fraction
from html.parser import HTMLParser
from pathlib import PurePosixPath
import re

from studio.native_media_visibility import Element, NativeElements, SAFE_ID, decimal_text, seconds
from studio.native_stage_evidence import require

COMPOSITION = 'data-composition-id'
SOURCE = 'data-composition-src'
TIMING = ('data-start', 'data-duration')
MEDIA_TAGS = frozenset({'audio', 'video', 'iframe', 'frame', 'object', 'embed'})
MOUNT_FILE = re.compile(r'compositions/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.html\Z')


def owning_composition(node: Element) -> Element | None:
    """Return the nearest ancestor that declares a composition, or None at top level."""
    current = node.parent
    while current is not None and COMPOSITION not in current.attrs:
        current = current.parent
    return current


def on_root_clock(node: Element, root: Element) -> bool:
    """Every container between a mount and the root must be untimed, like the root itself."""
    current = node.parent
    while current is not root:
        if any(key in current.attrs for key in TIMING) or 'clip' in (current.attrs.get('class') or '').split():
            return False
        current = current.parent
    return True


def mount_path(value: str | None) -> str:
    """Admit one canonical project-relative composition file, never a traversal or URL."""
    require(isinstance(value, str) and MOUNT_FILE.fullmatch(value) is not None
            and '..' not in PurePosixPath(value).parts and PurePosixPath(value).as_posix() == value,
            'catalog mount must name a local compositions/*.html file')
    return value


def mount_row(node: Element, root: Element, duration: Fraction) -> dict:
    """Validate one nested mount host and describe its exact root-clock window."""
    attrs = node.attrs
    require(SOURCE in attrs, 'nested inline compositions are unsupported in review')
    require(owning_composition(node) is root, 'catalog mount is nested inside another composition')
    require(not node.children and not node.has_text, 'catalog mount host must be empty')
    require(on_root_clock(node, root), 'catalog mount must use the root composition clock')
    require(SAFE_ID.fullmatch(attrs[COMPOSITION] or '') is not None, 'invalid catalog mount identity')
    start, length = seconds(attrs.get('data-start')), seconds(attrs.get('data-duration'))
    require(length > 0 and start + length <= duration + Fraction(1, 10**9), 'catalog mount window exceeds the canvas')
    require(all(str(attrs[key]).isdigit() and 0 < int(attrs[key]) <= 16384
                for key in ('data-width', 'data-height') if key in attrs), 'invalid catalog mount dimensions')
    return {'elementId': attrs.get('id'), 'compositionId': attrs[COMPOSITION], 'file': mount_path(attrs[SOURCE]),
            'startSeconds': decimal_text(start), 'endSecondsExclusive': decimal_text(start + length)}


def composition_root(elements: NativeElements, duration: Fraction) -> tuple[Element, list[dict]]:
    """Return the single top-level native composition and every mount it provably contains."""
    nodes = [node for node in elements.elements if COMPOSITION in node.attrs]
    top = [node for node in nodes if owning_composition(node) is None]
    require(all(SOURCE not in node.attrs for node in top), 'catalog composition mount is outside the native canvas root')
    require(len(top) == 1, 'review requires one standalone native composition root')
    root = top[0]
    mounts = [mount_row(node, root, duration) for node in nodes if node is not root]
    identities = [root.attrs[COMPOSITION], *(row['compositionId'] for row in mounts)]
    require(len(set(identities)) == len(identities), 'duplicate native composition identity')
    return root, mounts


class MountedTags(HTMLParser):
    """Record start tags of a mounted composition without judging its authored layout."""

    def __init__(self, source: str) -> None:
        """Parse once; script and style bodies stay opaque text."""
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Keep each element name and its attributes."""
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Self-closing syntax is still an element."""
        self.handle_starttag(tag, attrs)


def require_media_free(source: str) -> None:
    """A mounted file may not add sound, video or further mounts the review cannot account for."""
    tags = MountedTags(source).tags
    require(not any(tag in MEDIA_TAGS for tag, _attrs in tags),
            'mounted composition contains media the review cannot replace or gate')
    require(not any(SOURCE in attrs for _tag, attrs in tags), 'mounted composition mounts another composition')
