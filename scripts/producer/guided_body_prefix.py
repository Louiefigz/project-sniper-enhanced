"""Bind actual body placement to the held restricted opening's rendered graph.

This adapter grants no execution or approval authority. Its caller must hold
the authentic original result and current input/lease. The old result stores
actual assets and order, not clip dictionaries: only the exact pinned
own-screen implementation below permits that explicitly recorded derivation.
The existing oracle still compares every pre-encode core/review frame.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import digest, file_hash
from graphics.owned_execution import GraphicsComposition
from guided_opening_frames import executable_frames, full_program_frames
from guided_opening_inputs import OpeningInputs, closed
from guided_opening_result import read_graphics
from opening_prefix_contract import (CompositorPrefixRequest, HeldPrefixInput,
                                     PrefixClock, PrefixRanges)
from guided_caption_projection import HeldCaptionProjection
from guided_caption_layers import caption_page_clips, caption_prefix_request
from guided_presenter_body_prefix import presenter_body_prefix

DERIVATION_POLICY = "pinned-opening-own-screen-origin-v1"
_SOURCE = "scripts/producer/guided_opening_graphics.py"
_POLICY = {"policy": "global-composition-then-half-open-frame-trim-v1",
    "orderPolicy": "ordinary-outStart-ascending-stable-candidate-ties",
    "placementScope": "declared-own-screen-full-canvas-not-free-space-or-perceptual-proof"}


@dataclass(frozen=True)
class BodyPrefixBinding:
    """Separately authenticated original inputs/result, never directory selection."""

    inputs: OpeningInputs
    original_result: dict
    original_root: Path
    captions: HeldCaptionProjection | None = None


def _pinned_derivation(record: dict) -> dict:
    """Refuse to apply current projection rules to an unknown original producer."""
    path = Path(__file__).resolve().parent / "guided_opening_graphics.py"
    expected = {"path": _SOURCE, "sha256": file_hash(path)}
    rows = record["pipeline"]["executionClosure"]
    matching = [row for row in rows if row.get("path") == _SOURCE]
    if matching != [expected]:
        raise RuntimeError("body prefix opening graph derivation source is absent or stale")
    if any(record["pictures"].get(key) != value for key, value in _POLICY.items()):
        raise RuntimeError("body prefix original picture policy is unsupported")
    return expected


def _reference(row: dict) -> HeldPrefixInput:
    """Project held actual file facts; the oracle reobserves all referenced bytes."""
    return HeldPrefixInput(row["path"], row["sha256"], row["sizeBytes"])


def _original_clip(row: dict, proof: dict) -> dict:
    """Mirror only the exact original own-screen `_one` projection, no layouts."""
    return {"path": proof["actualAsset"]["path"], "graphicId": row["graphicId"],
        "outStart": row["entry"]["outStart"], "outEnd": row["entry"]["outEnd"],
        "anchor": "own-screen", "x": 0, "y": 0,
        "startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"]}


def derive_original_graph(binding: BodyPrefixBinding) -> tuple[tuple[dict, ...], dict]:
    """Verify actual proof refs/order before deriving the restricted old graph."""
    inputs, record = binding.inputs, binding.original_result
    expected = {"inputPath": str(inputs.path), "inputSha256": inputs.sha256,
        "executionId": inputs.value["executionId"], "executionInputHash": inputs.value["executionInputHash"],
        "documents": inputs.value["documents"], "authority": inputs.documents["authority"]}
    if any(digest(record[key]) != digest(value) for key, value in expected.items()):
        raise RuntimeError("body prefix original result/input/range authority differs")
    rows = executable_frames(binding.inputs)
    source = _pinned_derivation(record)
    read_graphics(record, rows, binding.original_root)
    clips = tuple(_original_clip(row, proof) for row, proof in zip(rows, record["graphics"]))
    evidence = {"schemaVersion": 1, "kind": "held-opening-graph-derivation", "policy": DERIVATION_POLICY,
        "scope": "pinned-restricted-projection-of-held-assets-not-literal-captured-graph-or-approval",
        "source": source, "inputSha256": binding.inputs.sha256,
        "originalResultReceiptHash": record["receiptHash"], "graphHash": digest(list(clips)),
        "candidateOrder": record["pictures"]["candidateOrder"],
        "executedOrder": record["pictures"]["executedOrder"]}
    return clips, evidence


def _actual_clip(clip: dict, row: dict, proof: dict, canvas: tuple[int, int]) -> None:
    """Bind actual ordinary clip geometry/order to the precise freshly proved asset."""
    keys = {"path", "outStart", "outEnd", "anchor", "x", "y", "startFrame", "endFrameExclusive", "placedBBox"}
    closed(clip, keys, "body ordinary own-screen clip")
    expected = {"path": proof["actualAsset"]["path"], "outStart": row["entry"]["outStart"],
        "outEnd": row["entry"]["outEnd"], "anchor": "own-screen", "x": 0, "y": 0,
        "startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"],
        "placedBBox": [0, 0, *canvas]}
    if digest(clip) != digest(expected) or proof["candidateOrder"] != row["order"] \
            or proof["graphicId"] != row["graphicId"] or proof["workerCleanupObserved"] is not True:
        raise RuntimeError("body actual clip differs from its ordered held graphic proof")
    asset = proof["actualAsset"]
    if (asset["width"], asset["height"]) != canvas:
        raise RuntimeError("body actual graphic is not the exact original full canvas")


def _composition(value: GraphicsComposition, binding: BodyPrefixBinding, proofs: list[dict]) -> list[dict]:
    """No timing, spatial, audio or unowned-asset transformation is admitted here."""
    authority = binding.inputs.documents["authority"]
    canvas = authority["target"]["width"], authority["target"]["height"]
    if value.video_in != binding.original_result["fullProgram"]["base"]["path"] \
            or value.canvas != canvas or value.frame_clock != (authority["frameRate"], authority["totalFrames"]):
        raise RuntimeError("body composition is not the exact held base/canvas/frame clock")
    options = value.options
    if not options.eof_pass or not options.video_only or options.ydif_file is not None \
            or options.frame_rate != authority["frameRate"] or options.frame_range is not None \
            or options.command_runner is not None or options.ffmpeg != "ffmpeg" or options.ffprobe != "ffprobe":
        raise RuntimeError("body composition options are not the full exact-frame picture path")
    rows = full_program_frames(binding.inputs)
    if len(value.clips) != len(rows) or len(proofs) != len(rows):
        raise RuntimeError("body composition omitted or added a candidate graphic")
    for clip, row, proof in zip(value.clips, rows, proofs):
        _actual_clip(clip, row, proof, canvas)
    return rows


def body_prefix_metadata(value: GraphicsComposition, binding: BodyPrefixBinding,
                         proofs: list[dict]) -> tuple[CompositorPrefixRequest, dict]:
    """Rebind base/graphics only; no returned data owns presenter execution."""
    _composition(value, binding, proofs)
    opening, evidence = derive_original_graph(binding)
    authority, record = binding.inputs.documents["authority"], binding.original_result
    assets = tuple(_reference(proof["actualAsset"]) for proof in (*proofs, *record["graphics"]))
    # Explicit keys avoid relying on any JSON object's insertion order.
    ranges = PrefixRanges((authority["core"]["startFrame"], authority["core"]["endFrameExclusive"]),
        (authority["review"]["startFrame"], authority["review"]["endFrameExclusive"]))
    clock = PrefixClock(authority["frameRate"], authority["totalFrames"], *value.canvas)
    request = CompositorPrefixRequest(_reference(record["fullProgram"]["base"]), assets,
        value.clips, opening, clock, ranges)
    return request, evidence


def body_prefix_captions(request: CompositorPrefixRequest, value: GraphicsComposition,
                         binding: BodyPrefixBinding, evidence: dict) -> tuple[CompositorPrefixRequest, dict]:
    """Append exactly the held caption pages for both live and data-only readers."""
    if binding.captions is not None:
        if digest(list(value.caption_clips)) != digest(list(caption_page_clips(binding.captions))):
            raise RuntimeError("body compositor lost its live original caption pages")
        request = caption_prefix_request(request, binding.captions)
        evidence = {**evidence, "captionProjectionHash": binding.captions.data_hash,
                    "combinedOpeningGraphHash": digest(list(request.opening_clips))}
    elif value.caption_clips:
        raise RuntimeError("body compositor has captions without original held projection")
    return request, evidence


def body_prefix_request(value: GraphicsComposition, binding: BodyPrefixBinding,
                        proofs: list[dict]) -> tuple[CompositorPrefixRequest, dict]:
    """Retain the actual full graph and attach only an independently live owner."""
    request, evidence = body_prefix_metadata(value, binding, proofs)
    request = presenter_body_prefix(request, value, binding)
    return body_prefix_captions(request, value, binding, evidence)
