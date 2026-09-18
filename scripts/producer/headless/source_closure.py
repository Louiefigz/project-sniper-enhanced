"""Strict local dependency discovery for sealed motion HTML and CSS."""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from html.parser import HTMLParser

_CSS_REF = re.compile(
    r"(?:@import\s+(?:url\(\s*)?|url\(\s*)"
    r'(?:"(?P<double>[^"]*)"|\'(?P<single>[^\']*)\'|'
    r"(?P<bare>[^'\"\s);]+))\s*\)?",
    re.IGNORECASE,
)
_JS_MODULE = re.compile(r"\b(?:import|export)\b", re.IGNORECASE)
_CSS_IMAGE_SET = re.compile(r"(?:-webkit-)?image-set\s*\(", re.IGNORECASE)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_FILE_ATTRS = {"data", "href", "poster", "src", "xlink:href"}
_BASE_FILES = ("hyperframes.json", "index.html", "package.json")


def _local_reference(raw: str) -> str | None:
    value = raw.strip()
    if not value or value.startswith("#") or value.lower().startswith("data:"):
        return None
    if value.startswith("//") or _SCHEME.match(value):
        raise RuntimeError("sealed composition has a remote render dependency")
    if (not value.startswith("/") or value.startswith("//") or "?" in value
            or "#" in value or "%" in value or "\\" in value):
        raise RuntimeError(f"render dependency is not canonical local input: {raw}")
    relative = value[1:]
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError(f"render dependency path is invalid: {raw}")
    return relative


def _css_references(css: str) -> set[str]:
    if _CSS_IMAGE_SET.search(css):
        raise RuntimeError("sealed render CSS image-set is unsupported")
    references = set()
    for match in _CSS_REF.finditer(css):
        raw = match.group("double", "single", "bare")
        value = next(item for item in raw if item is not None)
        relative = _local_reference(value)
        if relative is not None:
            references.add(relative)
    return references


class _HtmlReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: set[str] = set()
        self._style_depth = 0
        self._script_depth = 0

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "base":
            raise RuntimeError("sealed render HTML must not contain a base element")
        if tag.lower() == "style":
            self._style_depth += 1
        if tag.lower() == "script":
            self._script_depth += 1
        if (tag.lower() == "script"
                and any(key.lower() == "type"
                        and str(value).strip().lower() == "module"
                        for key, value in attrs)):
            raise RuntimeError("sealed render ES modules are unsupported")
        for key, value in attrs:
            self._attribute(key.lower(), value)

    def _attribute(self, key: str, value: str | None) -> None:
        if value is None:
            return
        if key in _FILE_ATTRS:
            self._add_reference(value)
            return
        if key == "srcset":
            self._srcset(value)
            return
        if key == "style":
            self.references.update(_css_references(value))

    def _add_reference(self, value: str) -> None:
        relative = _local_reference(value)
        if relative:
            self.references.add(relative)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style" and self._style_depth:
            self._style_depth -= 1
        if tag.lower() == "script" and self._script_depth:
            self._script_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            self.references.update(_css_references(data))
        if self._script_depth and _JS_MODULE.search(data):
            raise RuntimeError("sealed render ES modules are unsupported")

    def _srcset(self, value: str) -> None:
        for candidate in value.split(","):
            raw = candidate.strip().split(" ", 1)[0]
            self._add_reference(raw)


def _html_references(html: str) -> set[str]:
    parser = _HtmlReferences()
    parser.feed(html)
    parser.close()
    return parser.references


def _references(relative: str, data: bytes) -> set[str]:
    if not relative.endswith((".css", ".html", ".js", ".mjs", ".svg")):
        return set()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"render dependency is not UTF-8: {relative}") from exc
    if relative.endswith(".css"):
        return _css_references(text)
    if relative.endswith((".html", ".svg")):
        return _html_references(text)
    if _JS_MODULE.search(text):
        raise RuntimeError("sealed render ES modules are unsupported")
    return set()


def discover_source_set(compositions: Iterable[str], reader: Callable[[str], bytes]) -> dict[str, bytes]:
    """Read each shared dependency once per observation, with no persistent cache."""
    pending = set(_BASE_FILES)
    for composition in compositions:
        pending.update(_html_references(composition))
    sources: dict[str, bytes] = {}
    while pending:
        relative = min(pending)
        pending.remove(relative)
        if relative in sources:
            continue
        data = reader(relative)
        sources[relative] = data
        pending.update(_references(relative, data) - sources.keys())
    return sources


def discover_sources(composition_html: str, reader: Callable[[str], bytes]) -> dict[str, bytes]:
    """Read the recursively declared, root-relative local source closure."""
    return discover_source_set((composition_html,), reader)


def _read_root_source(root: str, relative: str) -> bytes:
    """Read one regular, non-symlink dependency below ``root``."""
    candidate = os.path.abspath(os.path.join(root, relative))
    if (os.path.commonpath((candidate, root)) != root
            or os.path.islink(candidate) or not os.path.isfile(candidate)):
        raise RuntimeError(f"invalid local render dependency: {relative}")
    with open(candidate, "rb") as handle:
        return handle.read()


def discover_root_sources(composition_html: str,
                          root: str) -> dict[str, bytes]:
    """Discover a composition's closure below one canonical local root."""
    canonical = os.path.abspath(root)
    if canonical != root or os.path.islink(root) or not os.path.isdir(root):
        raise RuntimeError("render source root is not a canonical directory")
    return discover_sources(
        composition_html, lambda relative: _read_root_source(root, relative))
