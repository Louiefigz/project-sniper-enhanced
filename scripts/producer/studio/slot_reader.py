"""Parse a Studio review project's ``index.html`` into host-slot state.

Studio persists operator edits by rewriting element attributes in the file
(``file-mutations`` API), so the file is generated-then-patched HTML whose
serialization details (quoting, entities, attribute order) are Studio's, not
ours. ``html.parser`` decodes it structurally; every value comparison happens
downstream on parsed data, never on raw text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from studio.sync_model import StudioSyncError

ROOT_ID = "review-root"
MEDIA_IDS = ("review-base", "review-base-audio")
_HEAD_TAGS = {"meta", "title", "link", "script", "style"}
_SKELETON_TAGS = {"html", "head", "body"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}


@dataclass(frozen=True)
class SlotElement:
    """One host-slot ``<div>`` as it currently sits in ``index.html``."""

    slot_id: str
    comp_id: str | None
    comp_src: str | None
    values_text: str | None
    start: float | None
    duration: float | None
    track_index: int | None
    z_index: int | None
    attrs: dict[str, str | None]


@dataclass
class IndexView:
    """The parsed review timeline: root, media, slots, and everything else."""

    root_attrs: dict[str, str | None] = field(default_factory=dict)
    media_attrs: dict[str, dict[str, str | None]] = field(default_factory=dict)
    slots: list[SlotElement] = field(default_factory=list)
    #: Elements the generator never writes — operator additions.
    unknown: list[str] = field(default_factory=list)
    #: Malformed structure that blocks a sync (duplicate ids, missing root).
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Element:
    tag: str
    attrs: dict[str, str | None]
    path: tuple[tuple[str, str], ...]  # open ancestors as (tag, id)

    def under(self, tag: str = "", el_id: str = "") -> bool:
        return any((not tag or t == tag) and (not el_id or i == el_id)
                   for t, i in self.path)


class _IndexParser(HTMLParser):
    """Collect every element with its attributes and ancestry."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[_Element] = []
        self._stack: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        record = dict(attrs)
        self.elements.append(
            _Element(tag, record, tuple(self._stack)))
        if tag not in _VOID_TAGS:
            self._stack.append((tag, record.get("id") or ""))

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.elements.append(_Element(tag, dict(attrs), tuple(self._stack)))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                return


def _parse_float(attrs: dict, key: str) -> float | None:
    value = attrs.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _css_props(style: str | None) -> dict[str, str]:
    """Inline-style declarations as a property map (syntax only)."""
    out: dict[str, str] = {}
    for chunk in (style or "").split(";"):
        name, sep, value = chunk.partition(":")
        if sep and name.strip():
            out[name.strip().lower()] = value.strip()
    return out


def _z_index(attrs: dict) -> int | None:
    value = _css_props(attrs.get("style")).get("z-index")
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None


def _slot_from(el: _Element) -> SlotElement:
    attrs = el.attrs
    track = _parse_float(attrs, "data-track-index")
    return SlotElement(
        slot_id=attrs.get("id") or "",
        comp_id=attrs.get("data-composition-id"),
        comp_src=attrs.get("data-composition-src"),
        values_text=attrs.get("data-variable-values"),
        start=_parse_float(attrs, "data-start"),
        duration=_parse_float(attrs, "data-duration"),
        track_index=int(track) if track is not None else None,
        z_index=_z_index(attrs),
        attrs=attrs)


def _describe(el: _Element) -> str:
    el_id = el.attrs.get("id")
    where = "head" if el.under("head") else \
        f"inside #{el.path[-1][1]}" if el.path and el.path[-1][1] else "body"
    return f"<{el.tag}{'#' + el_id if el_id else ''}> ({where})"


def _classify(el: _Element, view: IndexView, counts: dict[str, int]) -> None:
    """Route one element into the view; unknown means operator-added."""
    if el.tag in _SKELETON_TAGS:
        return
    if el.under("head"):
        if el.tag not in _HEAD_TAGS:
            view.unknown.append(_describe(el))
        return
    el_id = el.attrs.get("id") or ""
    if el_id == ROOT_ID:
        counts["root"] += 1
        view.root_attrs = el.attrs
        return
    if el_id in MEDIA_IDS and el.tag in ("video", "audio"):
        view.media_attrs[el_id] = el.attrs
        return
    if "data-composition-src" in el.attrs:
        view.slots.append(_slot_from(el))
        return
    if el.tag == "script" and not el.under(el_id=ROOT_ID):
        counts["body_scripts"] += 1
        if counts["body_scripts"] > 1:
            view.unknown.append("extra body-level <script>")
        return
    view.unknown.append(_describe(el))


def read_index(path: str) -> IndexView:
    """Parse ``index.html`` into an :class:`IndexView`.

    Args:
        path: The project's ``index.html``.

    Raises:
        StudioSyncError: The file is missing or has no review root.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise StudioSyncError(f"cannot read {path}: {exc}") from exc
    parser = _IndexParser()
    parser.feed(text)
    parser.close()
    view = IndexView()
    counts = {"root": 0, "body_scripts": 0}
    for el in parser.elements:
        _classify(el, view, counts)
    if counts["root"] != 1:
        raise StudioSyncError(
            f"index.html has {counts['root']} '{ROOT_ID}' elements — not a "
            "generated studio review project")
    seen: set[str] = set()
    for slot in view.slots:
        if not slot.slot_id:
            view.problems.append("host slot without an id attribute")
        elif slot.slot_id in seen:
            view.problems.append(f"duplicate host slot id '{slot.slot_id}'")
        seen.add(slot.slot_id)
    return view
