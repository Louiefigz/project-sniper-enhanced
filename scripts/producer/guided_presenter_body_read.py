"""Read held body presenter proof without creating an executable presenter owner.

The caller authenticates the stopped worker, base, captions, graphic assets and
tool bytes, and keeps its original source/deadline guard live. These checks bind
that retained evidence to independently reconstructed full/opening graphs. They
do not decode media, approve a video, or qualify caption/subject clearance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from guided_opening_inputs import closed, hash_value
from guided_presenter_assets import _absolute, _sha
from guided_presenter_read import (
    PresenterReadContext, PresenterReadEvidence, _read_guard, read_presenter_graphs, verify_opening_presenter_layers,
)
from opening_prefix_contract import CompositorPrefixRequest, HeldPrefixInput, _clock, canonical_hash, validate_caption_tail
from opening_prefix_graphs import PresenterGraphProjection, bounded_graph_json, presenter_projection_record

PRESENTER_ORACLE_FIELDS = frozenset({"schemaVersion", "kind", "scope", "status", "inputs", "implementation",
    "clock", "baseSelectedVideo", "graphicWorkload", "presenterObservations", "fullGraphHash", "openingGraphHash",
    "comparison", "layerPolicy", "encodedOutputObserved", "audioCompared", "approvalObserved", "audioAuthority",
    "timingMs", "cleanupScope"})


@dataclass(frozen=True)
class PresenterBodyReadContext:
    """Independently held reader inputs/tools and authenticated original pictures."""

    read: PresenterReadContext
    opening_pictures: dict
    tools: tuple[HeldPrefixInput, HeldPrefixInput]


def _exact(value: object, expected: object) -> bool:
    """Keep integer/float/bool distinctions outside cross-runtime hash normalization."""
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(_exact(value[key], item) for key, item in expected.items())
    if type(expected) is list:
        return len(value) == len(expected) and all(_exact(row, item) for row, item in zip(value, expected))
    return value == expected


def _tools(context: PresenterBodyReadContext) -> None:
    """Validate independently supplied held-tool metadata, never attach current stats."""
    if type(context.tools) is not tuple or len(context.tools) != 2 \
            or any(type(row) is not HeldPrefixInput for row in context.tools):
        raise RuntimeError("presenter body reader lacks independently held ffmpeg/ffprobe")
    for row in context.tools:
        if type(row.size_bytes) is not int or not 0 < row.size_bytes <= 1024 ** 3:
            raise RuntimeError("presenter body reader tool size is not an exact bounded integer")
        _absolute(row.path)
        _sha(row.sha256)


def _arguments(request: CompositorPrefixRequest, context: PresenterBodyReadContext) -> list:
    """Freeze read-only arguments; a serialized record can never attach a live owner."""
    if type(request) is not CompositorPrefixRequest or request.presenter is not None \
            or type(context) is not PresenterBodyReadContext or type(context.read) is not PresenterReadContext:
        raise RuntimeError("presenter body reader requires data-only metadata and independently held context")
    _tools(context)
    _clock(request.clock, request.ranges)
    validate_caption_tail(request)
    probe = context.read.ffprobe
    if context.tools[1] != HeldPrefixInput(probe.path, probe.sha256, probe.size_bytes) \
            or request.base != context.read.base:
        raise RuntimeError("presenter body reader base or probe differs from its held context")
    authority = context.read.inputs.documents["authority"]
    expected = {"frame_rate": authority["frameRate"], "total_frames": authority["totalFrames"],
                "width": authority["target"]["width"], "height": authority["target"]["height"]}
    spans = {name: [authority[name]["startFrame"], authority[name]["endFrameExclusive"]] for name in ("core", "review")}
    actual = {name: list(getattr(request.ranges, name)) for name in ("core", "review")}
    if canonical_hash(asdict(request.clock)) != canonical_hash(expected) or canonical_hash(actual) != canonical_hash(spans):
        raise RuntimeError("presenter body reader changed the original full clock or opening ranges")
    return [asdict(request.base), [asdict(row) for row in request.assets], list(request.full_clips),
            list(request.opening_clips), expected, spans, list(request.caption_tail) if request.caption_tail else None,
            [asdict(row) for row in context.tools], context.opening_pictures]


def _graph(request: CompositorPrefixRequest, evidence: PresenterReadEvidence, role: str) -> dict:
    """Use the same schema2 hash constructor as the live compositor, with data only."""
    full = role == "full"
    clips = request.full_clips if full else request.opening_clips
    tail = request.caption_tail[0 if full else 1] if request.caption_tail is not None else None
    payload = evidence.full if full else evidence.opening
    lane = PresenterGraphProjection(clips, tail, payload, tuple(HeldPrefixInput(**row) for row in evidence.assets))
    record = presenter_projection_record(request.clock, request.base, lane)
    bounded_graph_json(record)
    return record


def _layer_policy(request: CompositorPrefixRequest, evidence: PresenterReadEvidence) -> dict:
    """Bind whole future windows and exact caption tails, not only visible intro rows."""
    counts = request.caption_tail or (0, 0)
    return {"kind": "held-presenter-then-graphics-then-caption-pages-v1",
            "fullPresenterWindows": len(evidence.full["windows"]),
            "openingPresenterWindows": len(evidence.opening["windows"]) if evidence.opening is not None else 0,
            "fullCaptionTail": counts[0], "openingCaptionTail": counts[1]}


def _inventory(proof: dict, request: CompositorPrefixRequest,
               evidence: PresenterReadEvidence, context: PresenterBodyReadContext) -> None:
    """Every actual held asset and tool must occur once in the original oracle order."""
    rows = [asdict(request.base), *[asdict(row) for row in request.assets],
            *list(evidence.assets), *[asdict(row) for row in context.tools]]
    if len({row["path"] for row in rows}) != len(rows) \
            or not _exact(proof.get("inputs"), rows):
        raise RuntimeError("presenter body prefix lost its exact held base/asset/tool inventory")


def _comparison(proof: dict, request: CompositorPrefixRequest) -> None:
    """Require complete pre-encode ranges; saved hashes remain worker attestations."""
    comparison = closed(proof.get("comparison"), {"fullGraphPrefix", "core", "review"}, "presenter body comparison")
    full = closed(comparison["fullGraphPrefix"], {"sharedCompositorCommandHash", "observedCommandHash",
                  "frameCount", "pixelFormat", "frameHashesSha256"}, "presenter full prefix")
    if type(full["frameCount"]) is not int or full["frameCount"] != request.ranges.review[1] \
            or full["pixelFormat"] != "yuv420p":
        raise RuntimeError("presenter body prefix omits the full graph's original opening frames")
    for role in ("core", "review"):
        row, span = comparison[role], getattr(request.ranges, role)
        closed(row, set(full) | {"startFrame", "endFrameExclusive", "exactPreencodePixels"}, "presenter compared range")
        expected = {"startFrame": span[0], "endFrameExclusive": span[1], "frameCount": span[1] - span[0],
                    "pixelFormat": "yuv420p", "exactPreencodePixels": True}
        if any(type(row[key]) is not type(value) or row[key] != value for key, value in expected.items()):
            raise RuntimeError("presenter body prefix omits an exact complete original range")
    for row in comparison.values():
        for key in ("sharedCompositorCommandHash", "observedCommandHash", "frameHashesSha256"):
            hash_value(row[key])


def _composition(composition: dict, request: CompositorPrefixRequest, evidence: PresenterReadEvidence) -> dict:
    """A schema1 clip-only or caption-only proof cannot authenticate presenter work."""
    expected = {"schemaVersion": 2, "kind": "verified-presenter-prefix-private-picture-composition",
                "scope": "executed-graph-bound-picture-not-decoded-output-or-approval",
                "outputDecoded": False, "audioCompared": False, "deliveryApproved": False}
    if type(composition) is not dict or any(type(composition.get(key)) is not type(value)
            or composition[key] != value for key, value in expected.items()):
        raise RuntimeError("presenter body requires its schema2 private picture composition")
    output = closed(composition.get("output"), {"path", "sha256", "size_bytes"}, "presenter body encoded reference")
    if output["path"] != composition.get("outputPath") or type(output["size_bytes"]) is not int \
            or output["size_bytes"] <= 0:
        raise RuntimeError("presenter body composition lost its exact encoded output reference")
    hash_value(output["sha256"])
    proof = closed(composition.get("prefixOracle"), PRESENTER_ORACLE_FIELDS, "presenter body prefix oracle")
    expected = {"schemaVersion": 2, "kind": "presenter-compositor-prefix-oracle", "status": "verified",
                "scope": "executed-preencode-graph-prefix-not-encoded-output-or-approval",
                "clock": asdict(request.clock), "fullGraphHash": canonical_hash(_graph(request, evidence, "full")),
                "openingGraphHash": canonical_hash(_graph(request, evidence, "opening")),
                "layerPolicy": _layer_policy(request, evidence), "encodedOutputObserved": False,
                "audioCompared": False, "approvalObserved": False,
                "audioAuthority": "requires-separate-held-full-program-master-excerpt",
                "cleanupScope": "observed-owned-local-process-groups; no Docker invoked"}
    if type(proof) is not dict or any(not _exact(proof.get(key), value)
                                     for key, value in expected.items()):
        raise RuntimeError("presenter body proof changed its original full/opening graph, layers or scope")
    return proof


def verify_presenter_body_prefix(composition: dict, request: CompositorPrefixRequest,
                                 context: PresenterBodyReadContext) -> tuple[PresenterReadEvidence, PresenterReadEvidence]:
    """Reconstruct both held graphs without decoding, rendering or creating a live owner."""
    arguments = [composition, _arguments(request, context)]
    original, read = canonical_hash(arguments), context.read
    check = _read_guard(read, arguments)
    check()
    tail = request.caption_tail[1] if request.caption_tail is not None else None
    old = verify_opening_presenter_layers(context.opening_pictures, context.read, (request.opening_clips, tail))
    if old is None:
        raise RuntimeError("presenter body requires the original opening's held presenter evidence")
    proof = composition.get("prefixOracle") if type(composition) is dict else None
    if type(proof) is not dict:
        raise RuntimeError("presenter body has no original-worker prefix proof")
    current = read_presenter_graphs(proof.get("presenterObservations"), context.read)
    if current is None or canonical_hash([current.full, current.opening, list(current.assets)]) \
            != canonical_hash([old.full, old.opening, list(old.assets)]):
        raise RuntimeError("presenter body observations differ from the original opening's graph or sources")
    proof = _composition(composition, request, current)
    _inventory(proof, request, current, context)
    _comparison(proof, request)
    check()
    if context.read is not read or canonical_hash([composition, _arguments(request, context)]) != original:
        raise RuntimeError("presenter body proof or read context changed during verification")
    return old, current
