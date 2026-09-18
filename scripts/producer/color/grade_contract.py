"""Pure private grade intent; not an applied grade or decoder/approval receipt.

This frame-index declaration is deliberately NOT the seconds-based sampling
context. Its exact current hash is supplied by a future trusted observer. No
file, subprocess, renderer, canonical plan or approval is touched here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction

from cut_preview_io import digest
from graphics.render_rate import normalize_render_rate

MAX_FRAMES = 1_296_000
MAX_GROUPS = 12
POLICY = "sniper-private-source-grade-intent-v1"
_SHA = re.compile(r"[a-f0-9]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_BINDING_KEYS = {"sourceId", "sourceSha256", "admissionReceiptSha256",
                 "declarationSha256", "projectHistorySha256", "fps", "frameCount"}


def closed(value: object, keys: set[str], label: str) -> dict:
    """Reject optional/unknown fields instead of silently discarding intent."""
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def integer(value: object, minimum: int, maximum: int) -> int:
    """Keep frame indices and timestamps exact; booleans are not integers."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("grade integer is outside its explicit bound")
    return value


def identifier(value: object) -> str:
    """Accept bounded identifiers, never paths or executable strings."""
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("grade identifier is invalid")
    return value


@dataclass(frozen=True)
class SourceBinding:
    """Current observer-supplied identities; hashes alone do not prove admission."""

    source_id: str
    source_sha256: str
    admission_receipt_sha256: str
    declaration_sha256: str
    project_history_sha256: str
    fps: Fraction
    frame_count: int


def parse_source_binding(value: object) -> SourceBinding:
    """Require the render_rate-normalized token (``30``, not ``30/1``)."""
    row = closed(value, _BINDING_KEYS, "grade source binding")
    identifier(row["sourceId"])
    for key in _BINDING_KEYS - {"sourceId", "fps", "frameCount"}:
        if type(row[key]) is not str or _SHA.fullmatch(row[key]) is None:
            raise ValueError(f"grade binding {key} must be a lowercase SHA-256")
    if type(row["fps"]) is not str or len(row["fps"]) > 24:
        raise ValueError("grade FPS must be a reduced rational string")
    rate = normalize_render_rate(row["fps"])
    fps = Fraction(rate.numerator, rate.denominator)
    if rate.token != row["fps"] or not 1 <= fps <= 60:
        raise ValueError("grade FPS is outside the explicit 1..60 exact-rate class")
    count = integer(row["frameCount"], 1, MAX_FRAMES)
    if Fraction(count, 1) / fps > 21_600:
        raise ValueError("grade source exceeds six hours")
    return SourceBinding(row["sourceId"], row["sourceSha256"], row["admissionReceiptSha256"],
                         row["declarationSha256"], row["projectHistorySha256"], fps, count)


@dataclass(frozen=True)
class LightingGroup:
    """One explicit half-open source-frame interval, independent of output time."""

    group_id: str
    start_frame: int
    end_frame: int
    intent: str
    description: str


@dataclass(frozen=True)
class GradeDeclaration:
    """Operator-declared source context, never verified transform history."""

    source_id: str
    camera_profile: str | None
    transform_history: tuple[str, ...]
    groups: tuple[LightingGroup, ...]


def _text(value: object, maximum: int, empty: bool = True) -> str:
    """Bound declaration notes without interpreting prose as transformation code."""
    if type(value) is not str or not (0 if empty else 1) <= len(value) <= maximum:
        raise ValueError("grade declaration text is invalid")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise ValueError("grade declaration contains unsupported control characters")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("grade declaration contains non-UTF-8 surrogate characters")
    return value


def _groups(value: object, count: int) -> tuple[LightingGroup, ...]:
    """Require complete ordered coverage; gaps, overlap and reordering are errors."""
    if type(value) is not list or not 1 <= len(value) <= MAX_GROUPS:
        raise ValueError("grade lighting groups exceed their explicit bound")
    result, seen, position = [], set(), 0
    for value_row in value:
        row = closed(value_row, {"id", "startFrame", "endFrame", "intent", "description"}, "lighting group")
        group_id = identifier(row["id"])
        start = integer(row["startFrame"], 0, count - 1)
        end = integer(row["endFrame"], 1, count)
        if group_id in seen or start != position or end <= start:
            raise ValueError("grade groups must uniquely and completely cover source frames in order")
        if row["intent"] not in ("neutral", "dark", "colored", "unknown"):
            raise ValueError("grade lighting intent is unsupported")
        result.append(LightingGroup(group_id, start, end, row["intent"], _text(row["description"], 500)))
        seen.add(group_id)
        position = end
    if position != count:
        raise ValueError("grade groups do not cover the complete source")
    return tuple(result)


def parse_declaration(value: object, binding: SourceBinding) -> GradeDeclaration:
    """Bind exact current source/profile/history and frame-group declarations."""
    keys = {"schemaVersion", "sourceId", "sourceProfile", "cameraProfile",
            "historyState", "transformHistory", "lightingGroups"}
    row = closed(value, keys, "grade declaration")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1:
        raise ValueError("grade declaration schema is unsupported")
    if row["sourceId"] != binding.source_id:
        raise ValueError("grade declaration differs from the current source binding")
    if row["sourceProfile"] != "bt709-sdr" or row["historyState"] != "known":
        raise ValueError("grade requires explicit SDR BT.709 and known operator-declared history")
    camera = None if row["cameraProfile"] is None else _text(row["cameraProfile"], 200, False)
    history = row["transformHistory"]
    if type(history) is not list or len(history) > 20:
        raise ValueError("grade transform history exceeds its bound")
    parsed = GradeDeclaration(binding.source_id, camera,
                              tuple(_text(item, 500, False) for item in history),
                              _groups(row["lightingGroups"], binding.frame_count))
    if digest(row) != binding.declaration_sha256:
        raise ValueError("grade declaration differs from the current source binding")
    return parsed


@dataclass(frozen=True)
class LocalCorrection:
    """Unqualified encoded-luma/chroma intent, not EV or white balance."""

    group_id: str
    encoded_luma_offset: float
    contrast: float
    saturation: float

    @property
    def identity(self) -> bool:
        """Only the exact neutral triple is an identity intent."""
        return (self.encoded_luma_offset, self.contrast, self.saturation) == (0, 1, 1)


@dataclass(frozen=True)
class PrivateGradeRecipe:
    """Immutable parsed intent; no application/quality or decoder authority."""

    source: SourceBinding
    declaration: GradeDeclaration
    corrections: tuple[LocalCorrection, ...]
    look_name: str
    look_intensity: float

    @property
    def applicable(self) -> bool:
        """A future qualified compiler/worker/review path is required."""
        return False


def _amount(value: object, low: float, high: float) -> float:
    """Finite bounded numeric intent only; reject booleans and numeric strings."""
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError("grade numeric intent is outside its private bound")
    return float(value)


def _corrections(value: object, declaration: GradeDeclaration) -> tuple[LocalCorrection, ...]:
    """Pair every local correction to its declared group, with no inferred intent."""
    if type(value) is not list or len(value) != len(declaration.groups):
        raise ValueError("grade corrections must pair exactly with declared lighting groups")
    result = []
    for raw, group in zip(value, declaration.groups):
        row = closed(raw, {"groupId", "encodedLumaOffset", "contrast", "saturation"}, "local correction")
        if row["groupId"] != group.group_id:
            raise ValueError("grade correction group is missing, repeated or reordered")
        item = LocalCorrection(row["groupId"], _amount(row["encodedLumaOffset"], -0.04, 0.04),
                               _amount(row["contrast"], 0.9, 1.1), _amount(row["saturation"], 0.9, 1.1))
        if group.intent != "neutral" and not item.identity:
            raise ValueError("non-neutral/unknown lighting requires identity until an explicit reviewed workflow exists")
        result.append(item)
    return tuple(result)


def parse_grade_recipe(value: object, current_binding: object,
                       current_declaration: object) -> PrivateGradeRecipe:
    """Construct private intent only, with no observation/execution claim.

    Bounds do not establish filter math or clipping safety. The neutral triple
    and zero look intensity are identity INTENT, not proved pixel preservation.
    """
    row = closed(value, {"schemaVersion", "kind", "source", "corrections", "look"}, "grade recipe")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 or row["kind"] != POLICY:
        raise ValueError("private grade recipe schema is unsupported")
    binding = parse_source_binding(current_binding)
    if parse_source_binding(row["source"]) != binding:
        raise ValueError("grade recipe source/context/clock binding is stale")
    declaration = parse_declaration(current_declaration, binding)
    corrections = _corrections(row["corrections"], declaration)
    look = closed(row["look"], {"name", "intensity"}, "grade look")
    intensity = _amount(look["intensity"], 0, 1)
    if look["name"] not in ("neutral", "house-warm-v1") or (look["name"] == "neutral" and intensity != 0):
        raise ValueError("grade look is unsupported or has non-neutral intensity")
    if intensity and any(group.intent != "neutral" for group in declaration.groups):
        raise ValueError("common look cannot silently recolor intentional/unknown lighting")
    return PrivateGradeRecipe(binding, declaration, corrections,
                              look["name"] if intensity else "neutral", intensity)
