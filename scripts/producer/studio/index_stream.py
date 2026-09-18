"""Complete saved-index streams with only exact known host edit slots projected."""
from __future__ import annotations

import json
from html.parser import HTMLParser

from fingerprints import json_canon
from studio.declaration_sync import _object
from studio.slot_reader import SlotElement, _css_props, _VOID_TAGS

_NUMERIC_ATTRS = {"data-start", "data-duration", "data-track-index",
                  "data-width", "data-height", "data-fps", "data-volume"}


def _style(value: str) -> tuple:
    """Normalize declaration order, never discard duplicate or unsupported syntax."""
    chunks = [chunk for chunk in value.split(";") if chunk.strip()]
    names = [chunk.partition(":")[0].strip().lower() for chunk in chunks]
    if any(":" not in chunk for chunk in chunks) or len(names) != len(set(names)):
        raise ValueError("ambiguous saved inline style")
    return tuple(sorted(_css_props(value).items()))


def _attribute_value(name: str, value: str | None) -> object:
    """Preserve values except existing JSON/numeric/quote serialization freedom."""
    if value is None:
        return ""
    if name == "data-variable-values":
        return json.dumps(json_canon(json.loads(value, object_pairs_hook=_object)), sort_keys=True)
    if name == "style":
        return _style(value)
    if name in _NUMERIC_ATTRS:
        try:
            return repr(float(value))
        except ValueError:
            return value
    return value


def _semantic_attrs(attrs: list) -> tuple:
    """An attribute cannot disappear because a duplicate overwrote it in a dict."""
    if len(dict(attrs)) != len(attrs):
        raise ValueError("duplicate saved index attributes")
    return tuple(sorted((name, _attribute_value(name, value)) for name, value in attrs))


class _StreamParser(HTMLParser):
    """Keep all element/text/comment events and exact executable/style source."""

    def __init__(self) -> None:
        """Collect without resolving files or evaluating anything."""
        super().__init__(convert_charrefs=True)
        self.events: list[tuple] = []
        self.raw_tag = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Only normalized attributes enter the complete event stream."""
        self.events.append(("start", tag, _semantic_attrs(attrs)))
        if tag in ("script", "style"):
            self.raw_tag = tag

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """A self-closed nonvoid slot has the same empty structure as div/div."""
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """Preserve element boundaries; void tag spelling is serializer freedom."""
        if tag not in _VOID_TAGS:
            self.events.append(("end", tag))
        if tag == self.raw_tag:
            self.raw_tag = ""

    def handle_data(self, data: str) -> None:
        """HTML whitespace may serialize; script/style string bytes may not."""
        if self.raw_tag:
            self.events.append(("raw", data))
            return
        text = " ".join(data.split())
        if text:
            self.events.append(("text", text))

    def handle_comment(self, data: str) -> None:
        """Comments, including their contents, are pending edits rather than slots."""
        self.events.append(("comment", data))

    def handle_decl(self, decl: str) -> None:
        """Normalize only the ordinary doctype spelling, preserving its exact count."""
        normalized = " ".join(decl.lower().split())
        self.events.append(("declaration", "doctype html" if normalized == "doctype html" else decl))

    def handle_pi(self, data: str) -> None:
        """Processing instructions are user bytes, not serializer whitespace."""
        self.events.append(("instruction", data))

    def unknown_decl(self, data: str) -> None:
        """An unknown marked section cannot silently disappear from the comparison."""
        self.events.append(("unknown-declaration", data))


def _semantic_stream(text: str) -> list[tuple]:
    """Parse the entire saved document without executing or ignoring residuals."""
    parser = _StreamParser()
    parser.feed(text)
    parser.close()
    return parser.events


def _without_deleted(events: list[tuple], deleted: set[str]) -> list[tuple]:
    """Only a known original empty host can be removed from the baseline."""
    output, skip = [], False
    for index, event in enumerate(events):
        if skip:
            skip = False
            continue
        if event[:2] == ("start", "div") and dict(event[2]).get("id") in deleted:
            skip = _require_empty_host(events, index)
            continue
        output.append(event)
    return output


def _require_empty_host(events: list[tuple], index: int) -> bool:
    """Deletion never authorizes nested text, comments, scripts or other children."""
    if events[index + 1:index + 2] != [("end", "div")]:
        raise ValueError("original deleted host is not empty")
    return True


def _project_host(event: tuple, slots: dict[str, SlotElement]) -> tuple:
    """Ignore only supported values/timing and original view-only class/track/z."""
    if event[:2] != ("start", "div"):
        return event
    attrs = dict(event[2])
    slot = slots.get(attrs.get("id"))
    if slot is None:
        return event
    for key in ("data-variable-values", "data-start", "data-duration", "class"):
        attrs.pop(key, None)
    if slot.track_index is not None:
        attrs.pop("data-track-index", None)
    if slot.z_index is not None:
        style = dict(attrs.get("style", ()))
        style.pop("z-index", None)
        attrs["style"] = tuple(sorted(style.items()))
    return ("start", "div", tuple(sorted(attrs.items())))


def projected_index_stream(text: str, slots: dict[str, SlotElement],
                           deleted: set[str]) -> list[tuple]:
    """Project only supplied original hosts after capturing every semantic event."""
    return [_project_host(event, slots) for event in _without_deleted(_semantic_stream(text), deleted)]


def require_loaded_slots(text: str, slots: dict[str, SlotElement]) -> None:
    """The values being attributed must still be the actual originally loaded slots."""
    current = {dict(event[2]).get("id"): event[2] for event in _semantic_stream(text)
               if event[:2] == ("start", "div")}
    for ident, slot in slots.items():
        if current.get(ident) != _semantic_attrs(list(slot.attrs.items())):
            raise ValueError("index.html host changed during sync; reload its pending values")
