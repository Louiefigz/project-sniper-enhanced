"""Opt-in V1 identity geometry from supplied records, never decoder authority.

The historical V1 record schema/hash is unchanged. This separate, narrower
H.264 class requires explicit square SAR and consistent known chroma siting in
the header and EVERY original decoded frame. No rotation signaling may occur;
absence is not measured pixel orientation. No source conversion, RGB gamut
measurement, creative-look decision, presenter/base activation or approval is
provided. The authenticated held-record reader owns provenance and time.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from color.grade_frame_adapter import (
    finish_records, frame_records, normalized_frame, observed_stream,
)
from color.grade_observation_geometry import chroma_location, sample_aspect_ratio
from color.grade_source_class import SourceFrameValidator, SourceRecordValidation


@dataclass(frozen=True)
class Bt709IdentityMetadata:
    """Separate all-frame identity metadata, not a V2 transform observation."""

    codec: str
    chroma_location: str
    sample_aspect_ratio: str
    decoded_frame_count: int
    policy: str = field(default="bt709-v1-identity-metadata-v1", init=False)
    rotation_observation: str = field(default="no-stream-or-frame-rotation-metadata", init=False)
    pixel_orientation_measured: bool = field(default=False, init=False)


@dataclass(frozen=True)
class Bt709IdentityRecordValidation:
    """Supplied-record results only; callers cannot infer a decoder or source admission."""

    records: SourceRecordValidation
    metadata: Bt709IdentityMetadata
    record_validation_only: bool = field(default=True, init=False)
    decoder_execution_proved: bool = field(default=False, init=False)
    gamut_measured: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)


def _geometry(row: dict) -> tuple[str, str]:
    """Missing/nonidentity SAR and unknown chroma cannot acquire inferred defaults."""
    sar = sample_aspect_ratio(row.get("sample_aspect_ratio"))
    chroma = chroma_location(row.get("chroma_location"))
    if sar != "1:1" or chroma == "unavailable":
        raise ValueError("BT709 identity metadata requires explicit square SAR and known chroma siting")
    return sar, chroma


def _header(probe: dict, first: dict) -> tuple[str, str]:
    """Keep unrotated-signaling H.264 closed without treating absent tags as pixels."""
    streams = probe.get("streams")
    if type(streams) is not list or not 1 <= len(streams) <= 32 or any(type(row) is not dict for row in streams):
        raise ValueError("BT709 identity metadata has malformed stream records")
    video = [row for row in streams if row.get("codec_type") == "video"]
    if len(video) != 1:
        raise ValueError("BT709 identity metadata requires exactly one video stream")
    row, tags = video[0], video[0].get("tags", {})
    if row.get("codec_name") != "h264" or type(tags) is not dict \
            or any(type(key) is not str or key.casefold() == "rotate" for key in tags):
        raise ValueError("BT709 identity metadata requires H.264 without rotation tags")
    geometry = _geometry(row)
    if _geometry(first) != geometry:
        raise ValueError("BT709 identity stream and decoded geometry differ")
    return geometry


def validate_bt709_identity_records(context: tuple[dict, dict, dict], lines: Iterable[str],
                                   terminal: dict) -> Bt709IdentityRecordValidation:
    """Revalidate unchanged V1 records and supplemental geometry in one metadata pass."""
    binding, declaration, probe = context
    records = frame_records(lines)
    first = next(records, None)
    if first is None:
        raise ValueError("BT709 identity metadata has no decoded frames")
    geometry = _header(probe, first)
    scanner = SourceFrameValidator(binding, declaration, observed_stream(probe, binding, first))
    scanner.add_frame(normalized_frame(first, 0))
    for index, row in enumerate(records, start=1):
        if _geometry(row) != geometry:
            raise ValueError("BT709 identity decoded geometry changes across original frames")
        scanner.add_frame(normalized_frame(row, index))
    validated = finish_records(scanner, terminal, binding)
    metadata = Bt709IdentityMetadata("h264", geometry[1], geometry[0], validated.decoded_record_count)
    return Bt709IdentityRecordValidation(validated, metadata)
