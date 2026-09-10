#!/usr/bin/env python3
"""Immutable caption compiler context and exact destination clock helpers."""
from __future__ import annotations

from dataclasses import dataclass, field

from captions.caption_contract import CaptionContractError, SHA256_RE
from captions.caption_words import CaptionFrameRate


@dataclass(frozen=True)
class CaptionCompileContext:
    """All immutable inputs required to compile one caption generation."""

    track: object
    ledger: object
    words: object
    rate: CaptionFrameRate
    timeline_map_hash: str
    timeline_slices: dict[str, str] = field(default_factory=dict)
    style_inputs: dict[str, dict] = field(default_factory=dict)
    destination: dict = field(default_factory=dict)
    scene_windows: object = field(default_factory=list)
    segment_versions: dict[str, object] = field(default_factory=dict)
    sample_rate: int = 48_000
    max_shard_frames: int | None = None
    toolchain: object = None


def require_sha256(value: object, label: str) -> str:
    """Require a lowercase canonical SHA-256 digest."""
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise CaptionContractError(f"{label} must be a SHA-256 digest")
    return value


def validate_compile_context(context: object) -> CaptionCompileContext:
    """Validate context fields that must remain valid even with zero cues."""
    if not isinstance(context, CaptionCompileContext):
        raise CaptionContractError("caption compile context is malformed")
    if not isinstance(context.rate, CaptionFrameRate):
        raise CaptionContractError("caption context needs an exact frame rate")
    mappings = {
        "timeline slices": context.timeline_slices,
        "style inputs": context.style_inputs,
        "segment versions": context.segment_versions,
    }
    if any(not isinstance(value, dict) for value in mappings.values()):
        raise CaptionContractError("caption context mappings are malformed")
    require_sha256(context.timeline_map_hash, "caption timeline map")
    sample_rate = context.sample_rate
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) \
            or sample_rate < 1:
        raise CaptionContractError("caption sample rate must be positive")
    return context


def validate_destination(value: object) -> dict:
    """Validate the closed rectangular destination/safe-zone contract."""
    if not isinstance(value, dict):
        raise CaptionContractError("caption destination must be an object")
    required = {"profileId", "width", "height", "safeZones"}
    if set(value) != required:
        raise CaptionContractError(
            "caption destination has unknown or missing fields")
    width, height = value["width"], value["height"]
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0
           for item in (width, height)):
        raise CaptionContractError("caption destination dimensions are invalid")
    if not isinstance(value["profileId"], str) or not value["profileId"]:
        raise CaptionContractError("caption destination profileId is invalid")
    safe_zones = value["safeZones"]
    if not isinstance(safe_zones, dict) or set(safe_zones) != {
            "top", "bottom", "left", "right"}:
        raise CaptionContractError("caption destination safeZones are invalid")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0
           for item in safe_zones.values()):
        raise CaptionContractError("caption safe-zone insets are invalid")
    if safe_zones["top"] + safe_zones["bottom"] >= height \
            or safe_zones["left"] + safe_zones["right"] >= width:
        raise CaptionContractError("caption safe zones leave no visible region")
    return dict(value)


def max_shard_frames(context: CaptionCompileContext) -> int:
    """Resolve the explicit bound or the four-second default."""
    if context.max_shard_frames is not None:
        value = context.max_shard_frames
    else:
        rate = context.rate.fraction
        value = -(-(rate.numerator * 4) // rate.denominator)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CaptionContractError("max caption shard frames must be positive")
    return value


def sample_at_frame(frame: int, context: CaptionCompileContext) -> int:
    """Project a delivery-frame boundary onto the absolute sample clock."""
    rate = context.rate.fraction
    return frame * context.sample_rate * rate.denominator // rate.numerator
