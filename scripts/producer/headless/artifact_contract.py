"""Immutable artifact and decoded-media references for headless execution."""

from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass

_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_ARTIFACT_DEPTH = 32
_MAX_ARTIFACT_PART_BYTES = 255
_MAX_ARTIFACT_PATH_BYTES = 4096


class ArtifactContractError(RuntimeError):
    """An artifact path, digest, or media fact is not closed."""


@dataclass(frozen=True)
class ArtifactRefV1:
    """One root-relative immutable file binding."""

    relative_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class MediaFactsV1:
    """Decoded media facts with an authoritative rational frame rate."""

    width: int
    height: int
    duration_seconds: float
    fps_numerator: int
    fps_denominator: int
    frame_count: int
    size_bytes: int
    video_codec: str
    pixel_format: str
    profile: str
    alpha_mode: str
    audio_codec: str | None

    @property
    def fps(self) -> float:
        """Display FPS derived from the authoritative rational value."""
        return self.fps_numerator / self.fps_denominator


@dataclass(frozen=True)
class MediaRefV1:
    """Immutable media artifact plus facts measured from those exact bytes."""

    artifact: ArtifactRefV1
    facts: MediaFactsV1


def _bounded_filesystem_path(path: str, parts: list[str]) -> bool:
    try:
        encoded_path = path.encode("utf-8", errors="strict")
        encoded_parts = tuple(part.encode("utf-8", errors="strict") for part in parts)
    except UnicodeEncodeError:
        return False
    return (
        len(encoded_path) <= _MAX_ARTIFACT_PATH_BYTES
        and len(parts) <= _MAX_ARTIFACT_DEPTH
        and all(len(part) <= _MAX_ARTIFACT_PART_BYTES for part in encoded_parts)
    )


def _valid_relative(path: object) -> bool:
    if type(path) is not str or not path or "\\" in path:
        return False
    if unicodedata.normalize("NFC", path) != path:
        return False
    if any(unicodedata.category(character) == "Cc" for character in path):
        return False
    normalized = os.path.normpath(path)
    parts = path.split("/")
    return (
        normalized == path
        and not os.path.isabs(path)
        and all(part not in {"", ".", ".."} for part in parts)
        and _bounded_filesystem_path(path, parts)
    )


def validate_artifact_ref(value: object) -> None:
    """Require one normalized nonempty root-relative file reference."""
    valid = (
        type(value) is ArtifactRefV1
        and _valid_relative(value.relative_path)
        and type(value.sha256) is str
        and bool(_DIGEST.fullmatch(value.sha256))
        and type(value.size_bytes) is int
        and value.size_bytes > 0
    )
    if not valid:
        raise ArtifactContractError("artifact reference is invalid")


def validate_media_ref(value: object) -> None:
    """Require plausible complete media facts bound to artifact byte length."""
    if type(value) is not MediaRefV1 or type(value.facts) is not MediaFactsV1:
        raise ArtifactContractError("media reference is invalid")
    validate_artifact_ref(value.artifact)
    facts = value.facts
    integers = (
        facts.width,
        facts.height,
        facts.fps_numerator,
        facts.fps_denominator,
        facts.frame_count,
        facts.size_bytes,
    )
    numeric = (facts.duration_seconds, facts.fps)
    expected_duration = facts.frame_count / facts.fps
    tolerance = max(1.0 / facts.fps + 0.005, 0.04)
    valid = (
        all(type(item) is int and item > 0 for item in integers)
        and all(
            type(item) in {int, float} and math.isfinite(item) and item > 0
            for item in numeric
        )
        and facts.size_bytes == value.artifact.size_bytes
        and abs(facts.duration_seconds - expected_duration) <= tolerance
        and type(facts.video_codec) is str
        and bool(facts.video_codec)
        and type(facts.pixel_format) is str
        and bool(facts.pixel_format)
        and type(facts.profile) is str
        and bool(facts.profile)
        and facts.alpha_mode in {"none", "straight", "premultiplied"}
        and (
            facts.audio_codec is None
            or (type(facts.audio_codec) is str and bool(facts.audio_codec))
        )
    )
    if not valid:
        raise ArtifactContractError("media facts are invalid")
