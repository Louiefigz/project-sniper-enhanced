"""Measured media and prebound-clip checks for an approved R0 parent."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass

from .approved_parent_schema import ApprovedParentDescriptorV1
from .generation_artifact_store import GenerationArtifactStoreV1
from .media_probe import ProbeResultV1, artifact_sha256, probe_media_artifact
from .prebound_clips import (
    PreboundClipV1,
    parse_prebound_clips,
    validate_prebound_clips,
)
from .prebound_compositor_media import alpha_mode, assert_media, compatible
from .quality_pass_contract import GraphicAssetRefV1, MediaRefV1

_DIGEST = re.compile(r"[0-9a-f]{64}")


class ApprovedParentMediaError(RuntimeError):
    """Approved parent media or clip facts differ from measured bytes."""


@dataclass(frozen=True)
class ApprovedParentVerifierContextV1:
    """Exact probe binary and bounded allowance for parent verification."""

    ffprobe_path: str
    ffprobe_sha256: str
    timeout_seconds: float = 180.0


def validate_verifier_context(value: object) -> ApprovedParentVerifierContextV1:
    """Require an absolute exact probe tool and a bounded timeout."""
    if type(value) is not ApprovedParentVerifierContextV1:
        raise ApprovedParentMediaError("approved-parent verifier context is invalid")
    timeout = value.timeout_seconds
    path_valid = (
        os.path.isabs(value.ffprobe_path)
        and os.path.realpath(value.ffprobe_path) == value.ffprobe_path
        and os.path.normpath(value.ffprobe_path) == value.ffprobe_path
    )
    valid = (
        path_valid
        and bool(_DIGEST.fullmatch(value.ffprobe_sha256))
        and type(timeout) in {int, float}
        and math.isfinite(timeout)
        and 0 < timeout <= 3600
    )
    if not valid or artifact_sha256(value.ffprobe_path) != value.ffprobe_sha256:
        raise ApprovedParentMediaError("approved-parent probe tool is not admitted")
    return value


def _probe(
    store: GenerationArtifactStoreV1,
    media: MediaRefV1,
    context: ApprovedParentVerifierContextV1,
) -> ProbeResultV1:
    path = store.resolve(media.artifact)
    result = probe_media_artifact(path, context.ffprobe_path, context.timeout_seconds)
    try:
        assert_media(result, media)
    except RuntimeError as exc:
        raise ApprovedParentMediaError(str(exc)) from exc
    return result


def validate_parent_media(
    descriptor: ApprovedParentDescriptorV1,
    store: GenerationArtifactStoreV1,
    context: ApprovedParentVerifierContextV1,
) -> ProbeResultV1:
    """Probe exact base/final/graphic bytes and require the closed R0 media shape."""
    checked = validate_verifier_context(context)
    base = _probe(store, descriptor.base.media, checked)
    final = _probe(store, descriptor.output.final, checked)
    if not compatible(base, final) or base.sha256 == final.sha256:
        raise ApprovedParentMediaError("approved final is not a compatible composite")
    if (
        alpha_mode(base.pixel_format) != "none"
        or alpha_mode(final.pixel_format) != "none"
    ):
        raise ApprovedParentMediaError("base and final must be opaque media")
    for asset in descriptor.graphics.assets:
        graphic = _probe(store, asset.media, checked)
        if alpha_mode(graphic.pixel_format) != "straight" or graphic.audio_codec:
            raise ApprovedParentMediaError(
                "approved graphic must be silent alpha media"
            )
    return base


def _visible(
    clip: PreboundClipV1, asset: GraphicAssetRefV1, base: ProbeResultV1
) -> bool:
    width, height = asset.media.facts.width, asset.media.facts.height
    horizontal = clip.x < base.width and clip.x + width > 0
    vertical = clip.y < base.height and clip.y + height > 0
    return horizontal and vertical


def validate_parent_clips(
    descriptor: ApprovedParentDescriptorV1,
    store: GenerationArtifactStoreV1,
    plan: dict,
    base: ProbeResultV1,
) -> None:
    """Bind exact clip bytes and reject out-of-timeline or fully hidden overlays."""
    raw = store.read(descriptor.graphics.prebound_clips, 16 * 1024 * 1024)
    clips = parse_prebound_clips(raw)
    validate_prebound_clips(clips, plan, descriptor.graphics.assets)
    tolerance = max(base.fps_denominator / base.fps_numerator + 0.005, 0.04)
    for clip, asset in zip(clips, descriptor.graphics.assets):
        if clip.out_end > base.duration_seconds + tolerance or not _visible(
            clip, asset, base
        ):
            raise ApprovedParentMediaError(
                "prebound clip lies outside approved base visibility"
            )
