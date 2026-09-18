"""V2 original-source geometry/siting observations, with honest missing facts.

No rotation, chroma resampling or range conversion happens here. This bounded
class rejects signaled rotation/unknown side data; absence is recorded as such,
not as a measured pixel orientation. Missing siting/SAR are explicit unavailable
values and cannot serve as a transform default.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from color.grade_contract import closed
from color.grade_observation_profile import V2_PROFILE

_CHROMA = {"left", "center", "topleft", "top", "bottomleft", "bottom", "unavailable"}


def chroma_location(value: object) -> str:
    """Do not infer chroma position from codec, camera or common defaults."""
    if value in (None, "unspecified", "unknown", "N/A"):
        return "unavailable"
    if type(value) is not str or value not in _CHROMA:
        raise ValueError("v2 observation chroma location is unsupported")
    return value


def sample_aspect_ratio(value: object) -> str:
    """Preserve exact positive rational SAR; unknown is not square pixels."""
    if value in (None, "N/A", "0:1", "unknown", "unavailable"):
        return "unavailable"
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,5}:[1-9][0-9]{0,5}", value):
        raise ValueError("v2 observation sample aspect ratio is unsupported")
    n, d = map(int, value.split(":"))
    ratio = Fraction(n, d)
    if (ratio.numerator, ratio.denominator) != (n, d):
        raise ValueError("v2 observation sample aspect ratio is not reduced")
    return value


@dataclass(frozen=True)
class SourceObservationMetadata:
    """Every decoded frame matches the separate first-frame facts below."""

    codec: str
    stream_chroma_location: str
    decoded_chroma_location: str
    stream_sample_aspect_ratio: str
    decoded_sample_aspect_ratio: str

    def record(self) -> dict:
        """Closed observed facts, explicitly not transform eligibility/approval."""
        return {"profile": V2_PROFILE, "codec": self.codec, "transfer": "iec61966-2-4",
            "rotationObservation": "no-stream-rotation-metadata", "rotationDegrees": None,
            "streamChromaLocation": self.stream_chroma_location,
            "decodedChromaLocation": self.decoded_chroma_location,
            "streamSampleAspectRatio": self.stream_sample_aspect_ratio,
            "decodedSampleAspectRatio": self.decoded_sample_aspect_ratio,
            "transformApplicable": False}


def source_metadata(stream: dict, first: dict) -> dict:
    """Observe stream and decoded facts separately; never fill one from the other."""
    if stream.get("codec_name") != "h264" or "rotate" in stream.get("tags", {}):
        raise ValueError("v2 observation requires unrotated-signaling H.264 source")
    return SourceObservationMetadata("h264", chroma_location(stream.get("chroma_location")),
        chroma_location(first.get("chroma_location")), sample_aspect_ratio(stream.get("sample_aspect_ratio")),
        sample_aspect_ratio(first.get("sample_aspect_ratio"))).record()


def parse_source_metadata(value: object) -> SourceObservationMetadata:
    """Validate the explicit geometry observation; mixed known facts reject."""
    keys = set(SourceObservationMetadata("h264", "left", "left", "1:1", "1:1").record())
    row = closed(value, keys, "v2 observed source metadata")
    result = SourceObservationMetadata(row["codec"], chroma_location(row["streamChromaLocation"]),
        chroma_location(row["decodedChromaLocation"]), sample_aspect_ratio(row["streamSampleAspectRatio"]),
        sample_aspect_ratio(row["decodedSampleAspectRatio"]))
    if row != result.record() or row["codec"] != "h264" or row["transformApplicable"] is not False:
        raise ValueError("v2 source metadata is inconsistent or implies transformation")
    pairs = ((result.stream_chroma_location, result.decoded_chroma_location),
             (result.stream_sample_aspect_ratio, result.decoded_sample_aspect_ratio))
    if any(a != b and "unavailable" not in (a, b) for a, b in pairs):
        raise ValueError("v2 source stream/decoded geometry metadata differs")
    return result
