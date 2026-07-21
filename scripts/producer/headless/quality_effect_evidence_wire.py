"""Exact wire parser for SECTION_MARKER_ACCENT_V1 rendered evidence."""

from __future__ import annotations

import math
import re

from . import quality_receipt_json as wire
from .quality_evidence_types import (
    DecodedColorV1,
    EffectContrastV1,
    EffectLocalityV1,
    EffectPlacementV1,
    EffectProofV1,
    EffectTargetV1,
    EffectTimingV1,
    PreEncodeEffectV1,
    ProtectedRegionsV1,
)
from .quality_evidence_wire import (
    QualityEvidenceSchemaError,
    distinct_artifacts,
    integer,
    number,
    rgb,
)

_TOP_KEYS = frozenset(
    "approvedPlanDigest assemblyReceipt contrast decodedColor effectClass final "
    "locality placement plan preEncode protectedRegions qualityPolicyId "
    "requestDigest runtimeCapabilityManifest schemaVersion target timing verdict".split()
)
_TARGET_KEYS = frozenset(
    "brandMembership brandPolicyId graphicId relativePointer requestedValue".split()
)
_PREENCODE_KEYS = frozenset(
    "graphicMedia matchingPixels method rasterRgb renderIntentDigest".split()
)
_DECODED_KEYS = frozenset(
    "matchingFrames maximumDeltaEMilli method observedDeltaEMilli observedRgb "
    "requestedRgb sampledFrames".split()
)
_TIMING_KEYS = frozenset(
    "boundaryToleranceFrames expectedFirstFrame expectedLastFrame "
    "observedFirstFrame observedLastFrame outEnd outStart sampledFrames".split()
)
_PLACEMENT_KEYS = frozenset(
    "anchor deliveryHeight deliveryWidth expectedX expectedY graphicHeight "
    "graphicWidth maxOriginErrorPixels method observedX observedY".split()
)
_CONTRAST_KEYS = frozenset(
    "method observedMinimumMilliRatio passingFrames requiredMinimumMilliRatio "
    "sampledFrames".split()
)
_PROTECTED_KEYS = frozenset(
    "collisionFrames maximumOverlapPixels method regionKinds sampledFrames".split()
)
_LOCALITY_KEYS = frozenset(
    "decodedOutsideRoiMaterialPixels materialityThresholdMilli method "
    "observedMaxOutsideRoiDeltaMilli preencodeChangedPixels "
    "preencodeOutsideRoiChangedPixels".split()
)
_GRAPHIC_ID = re.compile(r"g-[0-9a-z]{8}")
_COLOR = re.compile(r"#[0-9A-F]{6}")


def _envelope(document: dict) -> None:
    row = wire.exact(document, _TOP_KEYS, "effect proof")
    valid = (
        type(row.get("schemaVersion")) is int
        and row["schemaVersion"] == 1
        and row.get("verdict") == "pass"
        and row.get("effectClass") == "SECTION_MARKER_ACCENT_V1"
    )
    if not valid:
        raise QualityEvidenceSchemaError("effect proof envelope is invalid")


def _target(value: object) -> EffectTargetV1:
    row = wire.exact(value, _TARGET_KEYS, "effect target")
    graphic_id = row["graphicId"]
    requested = row["requestedValue"]
    valid = (
        type(graphic_id) is str
        and bool(_GRAPHIC_ID.fullmatch(graphic_id))
        and row["relativePointer"] == "/spec/accent"
        and type(requested) is str
        and bool(_COLOR.fullmatch(requested))
        and row["brandMembership"] == "pass"
    )
    if not valid:
        raise QualityEvidenceSchemaError("effect target is invalid")
    return EffectTargetV1(
        graphic_id,
        row["relativePointer"],
        requested,
        wire.digest(row["brandPolicyId"], "brand policy ID"),
        row["brandMembership"],
    )


def _preencode(value: object) -> PreEncodeEffectV1:
    row = wire.exact(value, _PREENCODE_KEYS, "pre-encode effect evidence")
    method = row["method"]
    if method != "lossless-overlay-token-raster-v1":
        raise QualityEvidenceSchemaError("pre-encode effect method is invalid")
    return PreEncodeEffectV1(
        wire.artifact(row["graphicMedia"]),
        wire.digest(row["renderIntentDigest"], "render intent digest"),
        rgb(row["rasterRgb"], "pre-encode RGB"),
        integer(row["matchingPixels"], "pre-encode matching pixels", 1),
        method,
    )


def _decoded(value: object) -> DecodedColorV1:
    row = wire.exact(value, _DECODED_KEYS, "decoded color evidence")
    maximum = integer(row["maximumDeltaEMilli"], "maximum color delta", 0)
    observed = integer(row["observedDeltaEMilli"], "observed color delta", 0)
    sampled = integer(row["sampledFrames"], "decoded sampled frames", 1)
    matching = integer(row["matchingFrames"], "decoded matching frames", 1)
    requested_rgb = rgb(row["requestedRgb"], "requested decoded RGB")
    observed_rgb = rgb(row["observedRgb"], "observed decoded RGB")
    squared = sum((first - second) ** 2 for first, second in zip(requested_rgb, observed_rgb))
    calculated = int(round(math.sqrt(squared) * 1_000))
    valid = (
        row["method"] == "calibrated-rgb-euclidean-milli-v1"
        and maximum == 5_000
        and observed == calculated <= maximum
        and matching == sampled
    )
    if not valid:
        raise QualityEvidenceSchemaError("decoded color evidence is invalid")
    return DecodedColorV1(
        requested_rgb,
        observed_rgb,
        maximum,
        observed,
        sampled,
        matching,
        row["method"],
    )


def _timing(value: object) -> EffectTimingV1:
    row = wire.exact(value, _TIMING_KEYS, "effect timing evidence")
    start = number(row["outStart"], "effect outStart")
    end = number(row["outEnd"], "effect outEnd")
    expected_first = integer(row["expectedFirstFrame"], "expected first frame", 0)
    expected_last = integer(row["expectedLastFrame"], "expected last frame", 0)
    observed_first = integer(row["observedFirstFrame"], "observed first frame", 0)
    observed_last = integer(row["observedLastFrame"], "observed last frame", 0)
    tolerance = integer(row["boundaryToleranceFrames"], "timing tolerance", 0)
    sampled = integer(row["sampledFrames"], "timing sampled frames", 1)
    valid = end > start >= 0 and tolerance == 1 and expected_last >= expected_first
    valid = valid and abs(observed_first - expected_first) <= tolerance
    valid = valid and abs(observed_last - expected_last) <= tolerance
    valid = valid and observed_last >= observed_first
    valid = valid and sampled == expected_last - expected_first + 1
    if not valid:
        raise QualityEvidenceSchemaError("effect timing evidence is invalid")
    return EffectTimingV1(
        start,
        end,
        expected_first,
        expected_last,
        observed_first,
        observed_last,
        tolerance,
        sampled,
    )


def _placement(value: object) -> EffectPlacementV1:
    row = wire.exact(value, _PLACEMENT_KEYS, "effect placement evidence")
    expected_x = number(row["expectedX"], "expected x")
    expected_y = number(row["expectedY"], "expected y")
    observed_x = number(row["observedX"], "observed x")
    observed_y = number(row["observedY"], "observed y")
    tolerance = integer(row["maxOriginErrorPixels"], "placement tolerance", 0)
    dimensions = tuple(
        integer(row[key], f"placement {key}", 1)
        for key in ("deliveryWidth", "deliveryHeight", "graphicWidth", "graphicHeight")
    )
    valid = row["anchor"] == "free-band" and tolerance == 1
    valid = valid and row["method"] == "decoded-overlay-origin-v1"
    valid = valid and abs(observed_x - expected_x) <= tolerance
    valid = valid and abs(observed_y - expected_y) <= tolerance
    if not valid:
        raise QualityEvidenceSchemaError("effect placement evidence is invalid")
    return EffectPlacementV1(
        row["anchor"],
        expected_x,
        expected_y,
        observed_x,
        observed_y,
        tolerance,
        *dimensions,
        row["method"],
    )


def _contrast(value: object) -> EffectContrastV1:
    row = wire.exact(value, _CONTRAST_KEYS, "effect contrast evidence")
    required = integer(row["requiredMinimumMilliRatio"], "required contrast", 1)
    observed = integer(row["observedMinimumMilliRatio"], "observed contrast", 1)
    sampled = integer(row["sampledFrames"], "contrast sampled frames", 1)
    passing = integer(row["passingFrames"], "contrast passing frames", 1)
    valid = row["method"] == "decoded-moving-window-wcag-v1"
    valid = valid and required == 3_000 and observed >= required
    valid = valid and passing == sampled
    if not valid:
        raise QualityEvidenceSchemaError("effect contrast evidence is invalid")
    return EffectContrastV1(required, observed, sampled, passing, row["method"])


def _protected(value: object) -> ProtectedRegionsV1:
    row = wire.exact(value, _PROTECTED_KEYS, "protected-region evidence")
    sampled = integer(row["sampledFrames"], "protected sampled frames", 1)
    collisions = integer(row["collisionFrames"], "protected collisions", 0)
    overlap = integer(row["maximumOverlapPixels"], "protected overlap", 0)
    valid = row["regionKinds"] == ["caption", "title"]
    valid = valid and row["method"] == "decoded-region-intersection-v1"
    valid = valid and collisions == overlap == 0
    if not valid:
        raise QualityEvidenceSchemaError("protected-region evidence is invalid")
    return ProtectedRegionsV1(
        ("caption", "title"), sampled, collisions, overlap, row["method"]
    )


def _locality(value: object) -> EffectLocalityV1:
    row = wire.exact(value, _LOCALITY_KEYS, "effect locality evidence")
    changed = integer(row["preencodeChangedPixels"], "changed pixels", 1)
    pre_outside = integer(row["preencodeOutsideRoiChangedPixels"], "outside pixels", 0)
    material = integer(row["decodedOutsideRoiMaterialPixels"], "material pixels", 0)
    threshold = integer(row["materialityThresholdMilli"], "materiality threshold", 0)
    observed = integer(row["observedMaxOutsideRoiDeltaMilli"], "outside delta", 0)
    valid = row["method"] == "lossless-locality-calibrated-codec-spill-v1"
    valid = valid and pre_outside == material == 0 and threshold == 3_000
    valid = valid and observed <= threshold
    if not valid:
        raise QualityEvidenceSchemaError("effect locality evidence is invalid")
    return EffectLocalityV1(
        changed, pre_outside, material, threshold, observed, row["method"]
    )


def parse_effect_proof_v1(raw: object) -> EffectProofV1:
    """Parse exact requested-effect, contrast, placement, and locality evidence."""
    document = wire.canonical_document(raw, "effect proof")
    _envelope(document)
    refs = tuple(
        wire.artifact(document[key])
        for key in ("plan", "final", "assemblyReceipt", "runtimeCapabilityManifest")
    )
    preencode = _preencode(document["preEncode"])
    distinct_artifacts(refs + (preencode.graphic_media,), "effect proof")
    return EffectProofV1(
        refs[0],
        wire.digest(document["approvedPlanDigest"], "effect plan digest"),
        refs[1],
        refs[2],
        wire.digest(document["qualityPolicyId"], "effect quality policy ID"),
        refs[3],
        document["effectClass"],
        wire.digest(document["requestDigest"], "effect request digest"),
        _target(document["target"]),
        preencode,
        _decoded(document["decodedColor"]),
        _timing(document["timing"]),
        _placement(document["placement"]),
        _contrast(document["contrast"]),
        _protected(document["protectedRegions"]),
        _locality(document["locality"]),
        raw,
    )
