"""Strict, read-only Studio host remainder proof for GUI draft imports."""
from __future__ import annotations

import json
import math
import os
from html.parser import HTMLParser

with open(os.path.join(os.path.dirname(__file__), "copy-fields.json"), encoding="utf8") as _handle:
    COPY_FIELDS = {key: set(value) for key, value in json.load(_handle).items()}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}


def exact_json(value: object) -> str:
    """Type-exact JSON equality without bool/number collapse."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


class HostParser(HTMLParser):
    """Preserve code, comments, ancestry and every non-supported attribute."""

    def __init__(self, slots: dict[str, dict]) -> None:
        super().__init__(convert_charrefs=True)
        self.slots = slots
        self.events: list[tuple] = []
        self.values: dict[str, dict] = {}
        self.stack: list[str] = []
        self.ids: set[str] = set()
        self.hf_ids: set[str] = set()
        self.duration: float | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Extract only the exact supported slot values; keep the remainder."""
        keys = [key for key, _ in attrs]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate HTML attributes are unsupported")
        values = {key: "" if value is None else value for key, value in attrs}
        self._identity(values, "id", self.ids)
        self._identity(values, "data-hf-id", self.hf_ids)
        slot = values.get("id")
        if slot == "review-root":
            self.duration = float(values["data-duration"])
        if slot in self.slots:
            self.values[slot] = self._slot_values(values, self.slots[slot])
        self.events.append(("start", tag, tuple(sorted(values.items()))))
        if tag not in VOID:
            self.stack.append(tag)

    def _identity(self, attrs: dict, key: str, seen: set) -> None:
        value = attrs.get(key)
        if value is None:
            return
        if not value.strip() or value in seen:
            raise ValueError(f"Missing/duplicate {key} in Studio host")
        seen.add(value)

    def _slot_values(self, attrs: dict, entry: dict) -> dict:
        start = float(attrs.pop("data-start"))
        duration = float(attrs.pop("data-duration"))
        if not math.isfinite(start + duration) or start < 0 or duration <= 0:
            raise ValueError("Studio timing must be finite, nonnegative and have positive duration")
        spec = json.loads(attrs.pop("data-variable-values"))
        if not isinstance(spec, dict):
            raise ValueError("Studio slot variables must be an object")
        accepted = COPY_FIELDS.get(entry["kind"], set())
        remainder = {key: value for key, value in spec.items()
                     if key not in accepted}
        attrs["data-variable-values"] = exact_json(remainder)
        return {"start": start, "duration": duration, "spec": spec}

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Accept HTML void serialization; retain non-void self-closing shape."""
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """Malformed/changed ancestry is not serializer freedom."""
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            raise ValueError("Malformed Studio host ancestry")
        self.stack.pop()
        self.events.append(("end", tag))

    def handle_data(self, data: str) -> None:
        """Never normalize script/style or nonempty text whitespace."""
        if data.strip() or (self.stack and self.stack[-1] in {"script", "style"}):
            self.events.append(("text", data))

    def handle_comment(self, data: str) -> None:
        self.events.append(("comment", data))

    def handle_decl(self, decl: str) -> None:
        """Only equivalent HTML doctype spelling is serializer freedom."""
        if decl.strip().lower() != "doctype html":
            raise ValueError("Unsupported Studio document declaration")
        self.events.append(("doctype", "html"))

    def handle_pi(self, data: str) -> None:
        """Never silently discard unknown processing instructions."""
        raise ValueError("Studio processing instructions are unsupported")

    def unknown_decl(self, data: str) -> None:
        """Unknown declarations are code changes, not serializer freedom."""
        raise ValueError("Unsupported Studio document declaration")


def parse_host(text: str, entries: list[dict]) -> HostParser:
    """Parse one captured host; reject omitted or inserted slots."""
    slots = {entry["slot"]: entry for entry in entries}
    if len(slots) != len(entries):
        raise ValueError("Duplicate manifest slot identities")
    parser = HostParser(slots)
    parser.feed(text)
    parser.close()
    if parser.stack or set(parser.values) != set(slots):
        raise ValueError("Studio host structure or slot set changed")
    return parser


def prove_host(original: str, current: str, entries: list[dict]) -> tuple:
    """Every remaining event must match after removing only timing/copy."""
    before, after = parse_host(original, entries), parse_host(current, entries)
    if before.events != after.events:
        raise ValueError("Unsupported Studio code, structure, spatial, audio, or non-copy variable edit")
    if before.duration is None or not math.isfinite(before.duration):
        raise ValueError("Original Studio duration is unavailable")
    if any(row["start"] + row["duration"] > before.duration + 0.0001
           for row in after.values.values()):
        raise ValueError("Studio timing extends past the original base duration")
    return before.values, after.values
