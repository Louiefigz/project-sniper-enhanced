"""Data-only caption clearance beneath an independently authenticated opening.

The caller holds the stopped worker's actual result, original input/source
capture, base, tool, caption projection and graphic clips. Original observation
hashes remain worker attestations. No live presenter owner, decoder, renderer,
new deadline, source admission, face detection or approval is created here.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import stat

from cut_preview_io import digest
from guided_caption_dependencies import CaptionFile, read_caption_json
from guided_caption_layers import opening_caption_layers
from guided_caption_layout import _MAX_PAIRS, _clock, _cue, _span
from guided_caption_projection import CaptionProjectionBinding, HeldCaptionProjection
from guided_caption_screen import CaptionScreenContext, held_cues
from guided_opening_inputs import closed, hash_value
from guided_presenter_caption_clearance import GUTTER_PX, POLICY, _caption_identities, _pair
from guided_presenter_caption_picture import presenter_caption_picture_record
from guided_presenter_capture_inputs import PresenterCaptureSelection, capture_selection
from guided_presenter_profile import presenter_caption_profile
from guided_presenter_probe_identity import presenter_stat_identity
from guided_presenter_read import PresenterReadContext, PresenterReadEvidence, _layers, _read_guard, verify_opening_presenter_layers
from opening_prefix_contract import canonical_hash


def _json_hash(value: object) -> str:
    """Preserve in-memory numeric spelling while fencing callback-owned inputs."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _held_hash(held: HeldCaptionProjection) -> str:
    """Fence original Python types as well as the cross-runtime receipt hashes."""
    if type(held) is not HeldCaptionProjection or type(held.binding) is not CaptionProjectionBinding:
        raise RuntimeError("presenter caption read requires independently held captions")
    groups = (held.files, held.external, held.binding.dependencies,
              (held.binding.plan, held.binding.manifest, held.binding.timeline))
    if any(type(rows) is not tuple for rows in groups) \
            or any(type(row) is not CaptionFile for rows in groups for row in rows) \
            or type(held.binding.frame_clock) is not tuple:
        raise RuntimeError("presenter caption read held references changed type")
    return _json_hash({"root": held.root, "binding": asdict(held.binding), "data": held.data,
                      "data_hash": held.data_hash, "files": [asdict(row) for row in held.files],
                      "external": [asdict(row) for row in held.external]})


def _caption_identity_guard(held: HeldCaptionProjection) -> Callable[[], None]:
    """Validate canonical parents once, then fence the same nodes around byte reads.

    Initial stats are not byte authority: held_cues still performs its complete
    strong original hash read. These pre-read identities must survive it and
    every subsequent callback. No source-media bytes are rehashed here.
    """
    files = {Path(name): identity for name, identity in _caption_identities(held).items()}
    parents = {parent for path in files for parent in path.parents}
    directories = {}
    for path in parents:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("presenter caption read parent is no longer canonical")
        directories[path] = info.st_dev, info.st_ino, info.st_mode

    def check() -> None:
        """Cheap exact lstat fences avoid repeated resolve walks of shared parents."""
        for path, expected in directories.items():
            info = path.lstat()
            if (info.st_dev, info.st_ino, info.st_mode) != expected:
                raise RuntimeError("presenter caption cold read original parent changed")
        if any(presenter_stat_identity(path.lstat()) != identity for path, identity in files.items()):
            raise RuntimeError("presenter caption cold read original file changed")

    return check


def _guard(context: PresenterReadContext, held: HeldCaptionProjection,
           arguments: list) -> Callable[[], None]:
    """Bracket every callback with the same metadata and actual caption identities."""
    original, identity_check = _held_hash(held), _caption_identity_guard(held)
    source_check = _read_guard(context, arguments)
    metadata = lambda: _json_hash([context.inputs.value, context.inputs.documents, arguments])
    original_metadata = metadata()

    def check() -> None:
        """No callback may replace metadata or mutate a strongly read caption file."""
        identity_check()
        if _held_hash(held) != original or metadata() != original_metadata:
            raise RuntimeError("presenter caption cold read original dependencies changed")
        source_check()
        identity_check()
        if _held_hash(held) != original or metadata() != original_metadata:
            raise RuntimeError("presenter caption cold read original dependencies changed")

    return check


def _context(context: PresenterReadContext, held: HeldCaptionProjection) -> tuple:
    """Retain the original whole clock and exact opening review coverage."""
    inputs = context.inputs
    authority, plan = inputs.documents["authority"], inputs.documents["candidatePlan"]
    if authority.get("profile") != inputs.value["profile"] \
            or hash_value(authority["candidatePlanHash"]) != digest(plan):
        raise RuntimeError("presenter caption read candidate or profile differs from original authority")
    clock = _clock({"frameRate": authority["frameRate"], "totalFrames": authority["totalFrames"],
                    "width": authority["target"]["width"], "height": authority["target"]["height"]})
    coverage = closed(authority["review"], {"startFrame", "endFrameExclusive"}, "presenter caption read coverage")
    start, _end = _span(coverage, clock["totalFrames"])
    if start != 0:
        raise RuntimeError("presenter caption read cannot choose a partial safe review range")
    source = CaptionScreenContext(inputs, held, (), dict(coverage))
    return clock, source


def _cues(source: CaptionScreenContext, selection: PresenterCaptureSelection,
          clock: dict, check: Callable[[], None]) -> list[dict]:
    """Read complete original cue alpha extents; a page-local box is insufficient."""
    entries = source.held.data["shards"]["entries"]
    if type(entries) is not list or len(entries) > 4096 or len(entries) * len(selection.selected) > _MAX_PAIRS:
        raise RuntimeError("presenter caption read exceeds bounded cue/window pairs")
    raw = held_cues(source, check)
    plan = read_caption_json(source.held.binding.plan, check)
    if digest(plan) != digest(source.inputs.documents["candidatePlan"]):
        raise RuntimeError("presenter caption read differs from actual held candidate bytes")
    cues = []
    for cue in raw:
        check()
        cues.append(_cue(cue, clock))
    if len(cues) != len(entries) or len({cue["cueId"] for cue in cues}) != len(cues):
        raise RuntimeError("presenter caption read omitted or duplicated original cues")
    return cues


def _caption_layers(pictures: dict, layers: tuple, source: CaptionScreenContext) -> None:
    """Caller-owned graphic clips keep their order before the same original pages."""
    clips, tail = _layers(layers)
    if tail is None or tail > len(clips):
        raise RuntimeError("presenter caption read lacks its explicit original caption tail")
    graphics = list(clips[:-tail]) if tail else list(clips)
    combined, expected = opening_caption_layers(graphics, source.held, source.coverage["endFrameExclusive"])
    if canonical_hash(combined) != canonical_hash(list(clips)) \
            or digest(pictures.get("captionLayers")) != digest(expected):
        raise RuntimeError("presenter caption read lost exact original combined caption layers")


def _binding(source: CaptionScreenContext, clock: dict, evidence: PresenterReadEvidence, cues: list[dict]) -> dict:
    """Retain all original probe attestations and full/crossing/future graph rows."""
    inputs = source.inputs
    return {"executionInputHash": hash_value(inputs.value["executionInputHash"]),
        "candidatePlan": dict(inputs.value["documents"]["candidatePlan"]),
        "candidatePlanHash": digest(inputs.documents["candidatePlan"]),
        "authorityHash": digest(inputs.documents["authority"]), "captionProjectionHash": source.held.data_hash,
        "clock": clock, "coverage": dict(source.coverage), "presenterGraph": evidence.full,
        "presenterGraphHash": canonical_hash(evidence.full), "presenterObservations": list(evidence.observations),
        "cueBindingsHash": canonical_hash([{**cue, "box": list(cue["box"])} for cue in cues])}


def _report(binding: dict, selection: PresenterCaptureSelection,
            cues: list[dict], check: Callable[[], None]) -> dict:
    """Reuse the live inspector's swept-envelope/gutter math without a live owner."""
    pairs = []
    for window in selection.selected:
        check()
        # _pair consumes only operation_index and validated manual geometry.
        pairs.extend(row for cue in cues if (row := _pair(window, cue, binding["coverage"])) is not None)
    if any(row["conflict"] for row in pairs):
        raise RuntimeError("presenter caption read clearance conflicts with the original manual envelope")
    return {"schemaVersion": 1, "kind": "presenter-caption-clearance", "policy": POLICY,
        "scope": "precomposition-manual-envelope-not-face-or-presentation-text-readability",
        "state": "screened-no-overlap" if pairs else "not-applicable", "gutterPx": GUTTER_PX,
        "binding": binding, "intersections": pairs, "pictureProofBound": False,
        "qcPassed": False, "creativeApproved": False, "deliveryApproved": False}


def _types_match(actual: object, expected: object) -> bool:
    """Keep frame/flag types strict while accepting canonicalized integral floats."""
    if type(expected) is float:
        return type(actual) in (int, float)
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(_types_match(actual[key], value) for key, value in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_types_match(a, b) for a, b in zip(actual, expected))
    return True


def verify_presenter_caption_picture(pictures: dict, read_context: PresenterReadContext,
                                     held_captions: HeldCaptionProjection | None, combined_layers: tuple) -> None:
    """Reconstruct the closed original picture binding without minting execution."""
    if type(pictures) is not dict or type(read_context) is not PresenterReadContext:
        raise RuntimeError("presenter caption read requires original picture/read context")
    if not presenter_caption_profile(read_context.inputs.value.get("profile")):
        if "presenterCaptionClearance" in pictures:
            raise RuntimeError("uncaptioned or legacy opening acquired presenter caption clearance")
        return
    clips, tail = _layers(combined_layers)
    check = _guard(read_context, held_captions, [pictures, list(clips), tail])
    check()
    context = replace(read_context, guard=check)
    clock, source = _context(context, held_captions)
    selection = capture_selection(context.inputs)
    if selection is None or not selection.selected:
        raise RuntimeError("presenter caption read has no original selected windows")
    evidence = verify_opening_presenter_layers(pictures, context, (clips, tail))
    if evidence is None:
        raise RuntimeError("presenter caption read lacks original presenter range evidence")
    cues = _cues(source, selection, clock, check)
    _caption_layers(pictures, (clips, tail), source)
    report = _report(_binding(source, clock, evidence, cues), selection, cues, check)
    expected = presenter_caption_picture_record(report, pictures)
    actual = closed(pictures.get("presenterCaptionClearance"), set(expected), "presenter caption picture clearance")
    if not _types_match(actual, expected) or canonical_hash(actual) != canonical_hash(expected):
        raise RuntimeError("presenter caption picture differs from independently reconstructed clearance")
    check()
