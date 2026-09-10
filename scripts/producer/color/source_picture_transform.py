"""Compile one private picture-only float bridge; NEVER authorize its execution.

The owner supplies the actual returned BoundGradeObservation from the strong
read_observation path, not a status JSON or a reconstructed receipt. Its guard
must still hold source/parents/runtime bytes and the original deadline. Neither
that Python type nor this module's input hash authenticates an invocation.

No all-pixel gamut observer/receipt, output selection or renderer hook exists
here. A future owner must measure every native pixel of every original frame,
reject all non-finite/out-of-gamut values, and bind exact execution/clock/bytes
before allowing the destination fragment. Tiny test ramps cannot supply that
authority. No audio, WB, exposure, LUT, camera/history inference or tagging-only
conversion is performed by this compiler.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction

from color.grade_contract import integer, parse_source_binding
from color.grade_observation_geometry import SourceObservationMetadata, parse_source_metadata
from color.grade_observation_profile import V2, frame_budget
from color.grade_observation_read import BoundGradeObservation
from color.source_picture_transform_contract import (
    TRANSFORM_POLICY, bounded_json, parse_authority, parse_intent, parse_tools, sha256,
)
from color.source_picture_transform_reference import REFERENCE_POLICY
from cut_preview_io import digest


@dataclass(frozen=True)
class PictureTransformContext:
    """Live owner inputs; constructing this object proves no external authority."""

    observation: BoundGradeObservation
    authority: dict
    tools: dict


@dataclass(frozen=True)
class PictureTransformPlan:
    """Immutable compiler evidence only; there is intentionally no apply method."""

    input_hash: str
    measurement_filter: str
    destination_filter: str
    bindings_json: str
    executable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)

    def record(self) -> dict:
        """Return a detached non-selectable record with all missing proof explicit."""
        return {"schemaVersion": 1, "kind": TRANSFORM_POLICY, "inputHash": self.input_hash,
            "bindings": json.loads(self.bindings_json), "measurementFilter": self.measurement_filter,
            "destinationFilter": self.destination_filter, "executable": False,
            "gamutProof": "required-all-native-pixels-all-original-frames-not-supplied",
            "gamutTolerance": 0, "inputAutorotation": "disabled-required",
            "toolClosureVerification": "requires-owned-runtime-observation",
            "audioPolicy": "untouched-held-float-master-no-base-aac",
            "gradeApproved": False, "deliveryApproved": False}


def _clock(observation: BoundGradeObservation) -> dict:
    """Retain the original integer clock; no duration rounding or rebasing."""
    records, stream = observation.records, observation.records.stream
    source = records.source
    frame_budget(stream.width, stream.height, source.frame_count, V2)
    integer(stream.index, 0, 63)
    integer(stream.first_pts, -(2 ** 53 - 1), 2 ** 53 - 1)
    integer(stream.step_ticks, 1, 2 ** 53 - 1)
    integer(stream.first_pts + source.frame_count * stream.step_ticks, -(2 ** 53 - 1), 2 ** 53 - 1)
    if type(stream.time_base) is not Fraction or stream.time_base <= 0 \
            or 1 / (source.fps * stream.time_base) != stream.step_ticks:
        raise ValueError("picture transform original frame clock differs")
    return {"streamIndex": stream.index, "timeBase": str(stream.time_base),
        "firstPts": stream.first_pts, "stepTicks": stream.step_ticks, "fps": str(source.fps),
        "frames": source.frame_count, "width": stream.width, "height": stream.height}


def _observation(context: PictureTransformContext, authority: dict) -> dict:
    """Check relational eligibility; only the separately held owner proves origin."""
    held = context.observation
    if type(held) is not BoundGradeObservation:
        raise ValueError("picture transform needs a live bound observation, not status JSON")
    records = held.records
    if records.source != parse_source_binding(authority["binding"]) \
            or type(records.decoded_record_count) is not int \
            or records.decoded_record_count != records.source.frame_count:
        raise ValueError("picture transform observation source/coverage differs")
    if held.grade_applicable is not False or held.delivery_approved is not False \
            or records.record_validation_only is not True or records.decoder_execution_proved is not False \
            or records.grade_applicable is not False or records.delivery_approved is not False \
            or records.decoded_frame_flags_available is not False \
            or records.validator_policy != "sniper-private-grade-frame-records-v3":
        raise ValueError("picture transform observation has inconsistent authority scope")
    metadata = records.stream.source_metadata
    if type(metadata) is not SourceObservationMetadata:
        raise ValueError("picture transform requires the explicit V2 source observation")
    parse_source_metadata(metadata.record())
    if metadata.stream_chroma_location == "unavailable" \
            or metadata.stream_chroma_location != metadata.decoded_chroma_location \
            or metadata.stream_sample_aspect_ratio != "1:1" \
            or metadata.decoded_sample_aspect_ratio != "1:1":
        raise ValueError("picture transform requires exact known chroma siting and square SAR")
    return {"executionSha256": sha256(held.execution_sha256),
        "rawProbeSha256": sha256(held.raw_probe_sha256),
        "rawFramesSha256": sha256(held.raw_frames_sha256),
        "normalizedRecordsSha256": sha256(records.records_sha256),
        "validatorPolicy": records.validator_policy,
        "clock": _clock(held), "metadata": metadata.record(), "gradeApplicable": False}


def _filters(chroma: str) -> tuple[str, str]:
    """Fixed explicit math and spatial policy, with no raw plan filter insertion."""
    common = "w=iw:h=ih:filter=bilinear:dither=none:agamma=0"
    measure = (f"zscale={common}:pin=bt709:tin=iec61966-2-4:min=bt709:rin=tv:cin={chroma}:"
               "p=bt709:t=linear:m=gbr:r=full,format=gbrpf32le")
    destination = (f"zscale={common}:pin=bt709:tin=linear:min=gbr:rin=full:"
                   f"p=bt709:t=bt709:m=bt709:r=tv:c={chroma},format=yuv420p")
    return measure, destination


def _bindings(context: PictureTransformContext, intent: object) -> dict:
    """Snapshot complete compiler inputs; no supplied output/proof fields exist."""
    selected = parse_intent(intent)
    authority = parse_authority(context.authority)
    return {"intent": selected, "authority": authority, "tools": parse_tools(context.tools),
        "observation": _observation(context, authority), "scalarReference": REFERENCE_POLICY}


def compile_source_picture_transform(context: PictureTransformContext, intent: object,
                                     guard: Callable[[], None]) -> PictureTransformPlan:
    """Compile under the existing owner deadline; never create a fresh budget."""
    if type(context) is not PictureTransformContext or not callable(guard):
        raise ValueError("picture transform requires owned context and deadline guard")
    guard()
    observation = context.observation
    bindings = _bindings(context, intent)
    before = bounded_json(bindings)
    chroma = bindings["observation"]["metadata"]["decodedChromaLocation"]
    measure, destination = _filters(chroma)
    guard()
    if context.observation is not observation or bounded_json(_bindings(context, intent)) != before:
        raise RuntimeError("picture transform held inputs changed during compilation")
    result = PictureTransformPlan(digest({"bindings": bindings, "measurement": measure,
        "destination": destination}), measure, destination, before)
    guard()
    if context.observation is not observation or bounded_json(_bindings(context, intent)) != before:
        raise RuntimeError("picture transform held inputs changed before return")
    return result
