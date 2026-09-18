"""Media-reference and cover helpers for the prebound compositor."""

from __future__ import annotations

import json
import os

from .composite_media_checks import MediaCommandConfig, extract_frame_zero
from .media_probe import ProbeResultV1, artifact_sha256
from .prebound_compositor_store import CandidateStore
from .quality_pass_contract import (
    ArtifactRefV1,
    MediaFactsV1,
    MediaRefV1,
)

_R0_ALPHA_PIXEL_FORMATS = {"yuva444p12le"}


def alpha_mode(pixel_format: str) -> str:
    """Classify only the admitted R0 ProRes alpha pixel format as alpha."""
    return "straight" if pixel_format in _R0_ALPHA_PIXEL_FORMATS else "none"


def media_ref(relative: str, probe: ProbeResultV1) -> MediaRefV1:
    """Convert measured neutral facts to the shared immutable media contract."""
    alpha = alpha_mode(probe.pixel_format)
    facts = MediaFactsV1(
        probe.width,
        probe.height,
        probe.duration_seconds,
        probe.fps_numerator,
        probe.fps_denominator,
        probe.frame_count,
        probe.size_bytes,
        probe.video_codec,
        probe.pixel_format,
        probe.profile,
        alpha,
        probe.audio_codec,
    )
    artifact = ArtifactRefV1(relative, probe.sha256, probe.size_bytes)
    return MediaRefV1(artifact, facts)


def assert_media(probe: ProbeResultV1, expected: MediaRefV1) -> None:
    """Require materialized media bytes/facts to equal the sealed reference."""
    if media_ref(expected.artifact.relative_path, probe) != expected:
        raise RuntimeError("materialized media differs from sealed facts")


def compatible(base: ProbeResultV1, final: ProbeResultV1) -> bool:
    """Return whether composition preserved timeline, canvas, rate, and audio."""
    return (
        base.width,
        base.height,
        base.fps_numerator,
        base.fps_denominator,
        base.frame_count,
        base.audio_codec,
    ) == (
        final.width,
        final.height,
        final.fps_numerator,
        final.fps_denominator,
        final.frame_count,
        final.audio_codec,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("ascii")


def make_cover(
    store: CandidateStore, final: MediaRefV1, config: MediaCommandConfig
) -> tuple[ArtifactRefV1, ArtifactRefV1]:
    """Extract and prove exact encoded frame zero."""
    final_path = os.path.join(store.root, final.artifact.relative_path)
    pending = os.path.join(store.root, ".cover.pending.png")
    extract_frame_zero(final_path, pending, config)
    cover_path = store.promote(".cover.pending.png", "cover.png")
    cover = ArtifactRefV1(
        "cover.png", artifact_sha256(cover_path), os.stat(cover_path).st_size
    )
    proof = _canonical(
        {
            "schemaVersion": 1,
            "frameIndex": 0,
            "method": "ffmpeg-select-frame-zero-png",
            "sourceFinalSha256": final.artifact.sha256,
            "cover": {
                "path": cover.relative_path,
                "sha256": cover.sha256,
                "sizeBytes": cover.size_bytes,
            },
        }
    )
    return cover, store.write("cover-proof.json", proof)
