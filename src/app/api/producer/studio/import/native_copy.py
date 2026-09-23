"""Closed native text-to-variable proof; never infer arbitrary DOM semantics.

The pinned Studio text inspector writes plain DOM text, not host variables.
Only a reviewed selector with a proved source assignment can bridge that edit.
Every other HTML, script, style, attribute, declaration and ancestry stays bound.
"""
from __future__ import annotations

import copy
import json

from remainder import HostParser, VOID, exact_json

# Explicitly supported plain-text anatomy only. Rich text, generated lists and
# arbitrary selectors must not be guessed into a catalog variable.
_TEXT_BINDINGS = {"marker-highlight": {"mh-text": "text"}}


class CompositionParser(HostParser):
    """Compare parsed serializer output while retaining all executable content."""

    def __init__(self, bindings: dict[str, str]) -> None:
        super().__init__({})
        self.bindings = bindings
        self.declarations: list | None = None
        self.copy_values: dict[str, str] = {}
        self.active: tuple[int, str] | None = None
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Remove only one known declarations attribute and the named text leaf."""
        if self.active:
            raise ValueError("Native copy must remain a plain-text leaf, not markup")
        keys = [key for key, _ in attrs]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate composition attributes are unsupported")
        values = dict(attrs)
        if "data-composition-variables" in values:
            if tag != "html" or self.declarations is not None:
                raise ValueError("Composition declarations must occur once on html")
            declarations = json.loads(values.pop("data-composition-variables"))
            if not isinstance(declarations, list):
                raise ValueError("Composition declarations must be an array")
            self.declarations = declarations
        super().handle_starttag(tag, list(values.items()))
        field = self.bindings.get(values.get("id"))
        if field:
            if tag != "p" or field in self.copy_values:
                raise ValueError("Native copy selector has an unsupported shape")
            self.active, self.chunks = (len(self.stack), field), []
            self.events.append(("native-copy-leaf", field))

    def handle_data(self, data: str) -> None:
        """Only named plain-text content is excluded from the code remainder."""
        if self.active:
            self.chunks.append(data)
            return
        super().handle_data(data)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """HTML non-void self-closing syntax must not pretend to close a node."""
        if tag not in VOID and "svg" not in self.stack:
            raise ValueError("Self-closing HTML composition elements are unsupported")
        super().handle_startendtag(tag, attrs)

    def handle_comment(self, data: str) -> None:
        """Comments inside a supported text leaf are not editable text."""
        if self.active:
            raise ValueError("Native copy must not contain comments")
        super().handle_comment(data)

    def handle_endtag(self, tag: str) -> None:
        """Capture exact text before the shared strict ancestry check closes it."""
        if self.active and self.active[0] == len(self.stack):
            self.copy_values[self.active[1]] = "".join(self.chunks)
            self.active, self.chunks = None, []
        super().handle_endtag(tag)


def _parse(text: str, bindings: dict[str, str]) -> CompositionParser:
    """Require complete declarations, unique selectors, and balanced ancestry."""
    if "\x00" in text:
        raise ValueError("Native copy cannot preserve an HTML NUL character")
    parser = CompositionParser(bindings)
    parser.feed(text)
    parser.close()
    if parser.stack or parser.active or parser.declarations is None:
        raise ValueError("Composition code or declarations are incomplete")
    if set(parser.copy_values) != set(bindings.values()):
        raise ValueError("Native copy selector is missing or duplicated")
    return parser


def _native_changes(before: CompositionParser, after: CompositionParser) -> dict:
    """Return changed leaf strings only; no script/selector-based guessing."""
    if before.events != after.events:
        raise ValueError("Unsupported Studio composition code/structure edit")
    return {field: value for field, value in after.copy_values.items()
            if value != before.copy_values[field]}


def prove_composition_copy(original: str, current: str, changes: dict,
                           kind: str) -> dict:
    """Prove a native or declared-variable copy change against original bytes."""
    from studio.comp_transform import native_text_assignment
    bindings = _TEXT_BINDINGS.get(kind, {})
    before, after = _parse(original, bindings), _parse(current, bindings)
    if bindings:
        seeds = [row.get("default") for row in before.declarations
                 if row.get("id") == "text" and row.get("type") == "string"]
        if len(seeds) != 1 or not isinstance(seeds[0], str) or native_text_assignment(seeds[0]) not in original:
            raise ValueError("Native copy source-to-variable assignment is unproved")
    native = _native_changes(before, after)
    if any(field in changes and changes[field] != value
           for field, value in native.items()):
        raise ValueError("Native text and host-variable edits conflict")
    expected = copy.deepcopy(before.declarations)
    combined = {**changes, **native}
    for row in expected:
        if row.get("id") in combined:
            row["default"] = combined[row["id"]]
    # Native DOM editing leaves declarations untouched; a variable-panel edit
    # may update the exact paired defaults. No third declaration state is valid.
    if exact_json(after.declarations) not in {
            exact_json(before.declarations), exact_json(expected)}:
        raise ValueError("Unsupported Studio variable declaration edit")
    return native
