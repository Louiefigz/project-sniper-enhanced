"""Require composition defaults to agree with the authoritative host-slot edit.

This is a refusal boundary, not automatic panel-to-plan inference. Only the
existing host diff supplies plan values; unknown panel edits remain pending.
The caller must first verify the rebuilt original against its manifest hash.
"""
from __future__ import annotations

import json
from html.parser import HTMLParser

from fingerprints import json_canon


def _object(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON keys rather than silently choose a saved value."""
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate declaration JSON keys")
    return result


def _exact(value: object) -> str:
    """Preserve JSON types with only integral-number serialization equivalence."""
    return json.dumps(json_canon(value), sort_keys=True, allow_nan=False)


class _Declarations(HTMLParser):
    """Extract one actual html attribute, with normal quote/entity decoding."""

    def __init__(self) -> None:
        """Start without a declaration; comments and script strings are not attrs."""
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] | None = None
        self.tag_text = ""
        self.tag_position = (0, 0)
        self.other_attrs: tuple = ()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """A duplicate or retargeted declarations attribute cannot be adopted."""
        values = [value for key, value in attrs if key == "data-composition-variables"]
        if not values:
            return
        if tag != "html" or len(values) != 1 or self.rows is not None \
                or len(dict(attrs)) != len(attrs) or not isinstance(values[0], str):
            raise ValueError("composition declarations must occur once on html")
        rows = json.loads(values[0], object_pairs_hook=_object)
        if not isinstance(rows, list) or any(type(row) is not dict for row in rows):
            raise ValueError("composition declarations must be an array of objects")
        ids = [row.get("id") for row in rows]
        if any(type(key) is not str or not key for key in ids) or len(set(ids)) != len(ids):
            raise ValueError("composition declaration IDs must be unique strings")
        _exact(rows)
        self.rows = rows
        self.tag_text = self.get_starttag_text()
        self.tag_position = self.getpos()
        self.other_attrs = tuple((key, value) for key, value in attrs if key != "data-composition-variables")


def _read(source: str) -> _Declarations:
    """Reject absent declarations and nonfinite JSON instead of guessing defaults."""
    parser = _Declarations()
    parser.feed(source)
    parser.close()
    if parser.rows is None:
        raise ValueError("composition declarations are missing")
    return parser


def _parse(source: str) -> list[dict]:
    """Return the same strictly parsed rows used by the paired-value gate."""
    parser = _read(source)
    assert parser.rows is not None
    return parser.rows


def declaration_projection(source: str) -> tuple[tuple, list[dict]]:
    """Compare declaration data while retaining all bytes outside its root tag.

    The existing HTML parser supplies the actual tag position and decoded
    attributes. This is note-only comparison data, never rewritten HTML or
    permission to adopt a changed default. Other root attributes stay ordered.
    """
    parser = _read(source)
    line, column = parser.tag_position
    offset = sum(len(part) + 1 for part in source.split("\n")[:line - 1]) + column
    end = offset + len(parser.tag_text)
    if source[offset:end] != parser.tag_text:
        raise ValueError("composition declaration position is unavailable")
    assert parser.rows is not None
    return (source[:offset], parser.other_attrs, source[end:]), parser.rows


def require_paired_declarations(original: str, current: str, host_spec: dict) -> None:
    """Permit only unchanged rows or exact defaults paired with current host values."""
    before, after = _parse(original), _parse(current)
    if len(before) != len(after):
        raise ValueError("composition declaration set changed")
    for old, new in zip(before, after):
        if set(old) != set(new) or _exact({key: value for key, value in old.items() if key != "default"}) \
                != _exact({key: value for key, value in new.items() if key != "default"}):
            raise ValueError("composition declaration identity, type or metadata changed")
        if _exact(old.get("default")) == _exact(new.get("default")):
            continue
        key = old["id"]
        if key not in host_spec or _exact(host_spec[key]) != _exact(new["default"]):
            raise ValueError(f"unmatched declared default {key!r}; preserve the Studio edit and "
                             "resolve it into the matching host-slot value before syncing")
